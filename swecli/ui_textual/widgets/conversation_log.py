"""Conversation log widget with markdown-aware rendering and tool formatting."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, List, TYPE_CHECKING

from rich.console import RenderableType
from rich.text import Text
from textual.events import MouseDown, MouseMove, MouseScrollDown, MouseScrollUp, MouseUp, Resize
from textual.geometry import Size
from textual.widgets import RichLog
from swecli.ui_textual.style_tokens import SUBTLE, CYAN

if TYPE_CHECKING:
    from typing_extensions import Self

# Resize reflow constants
MAX_RENDERABLE_ENTRIES = 500
RERENDER_BATCH_SIZE = 50
RESIZE_DEBOUNCE_MS = 200
WIDTH_CHANGE_THRESHOLD = 5


@dataclass
class RenderableEntry:
    """Stores original renderable for re-rendering on resize."""
    renderable: RenderableType
    line_start: int
    line_count: int

from swecli.ui_textual.widgets.conversation.spinner_manager import DefaultSpinnerManager
from swecli.ui_textual.widgets.conversation.message_renderer import DefaultMessageRenderer
from swecli.ui_textual.widgets.conversation.tool_renderer import DefaultToolRenderer
from swecli.ui_textual.widgets.conversation.scroll_controller import DefaultScrollController


class ConversationLog(RichLog):
    """Enhanced RichLog for conversation display with scrolling support."""

    can_focus = True
    ALLOW_SELECT = True

    def __init__(self, **kwargs):
        super().__init__(
            **kwargs,
            wrap=True,
            highlight=True,
            markup=True,
            auto_scroll=True,
            max_lines=10000,
        )
        self._scroll_controller = DefaultScrollController(self, None)
        self._spinner_manager = DefaultSpinnerManager(self, None)
        self._message_renderer = DefaultMessageRenderer(self, None)
        self._tool_renderer = DefaultToolRenderer(self, None)
        
        self._last_assistant_rendered: str | None = None
        self._spinner_active = False
        self._approval_start: int | None = None
        self._debug_enabled = False  # Enable debug messages by default
        self._protected_lines: set[int] = set()  # Lines that should not be truncated
        self.MAX_PROTECTED_LINES = 200

        # Resize reflow state
        self._renderable_entries: deque[RenderableEntry] = deque(maxlen=MAX_RENDERABLE_ENTRIES)
        self._last_render_width: int = 0
        self._is_rerendering: bool = False
        self._resize_timer: Any | None = None
        self._skip_renderable_storage: bool = False  # Flag for temporary content (spinner)
        
    def refresh_line(self, y: int) -> None:
        """Refresh a specific line by invalidating cache and repainting."""
        # Aggressively clear cache to ensure spinner animation updates
        if hasattr(self, '_line_cache'):
            self._line_cache.clear()
        self.refresh()

    def write(
        self,
        content: RenderableType | object,
        width: int | None = None,
        expand: bool = False,
        shrink: bool = True,
        scroll_end: bool | None = None,
        animate: bool = False,
    ) -> "Self":
        """Extended write that stores original renderables for resize reflow."""
        # Skip storage during re-render OR for temporary content (spinner)
        if self._is_rerendering or self._skip_renderable_storage:
            return super().write(content, width, expand, shrink, scroll_end, animate)

        lines_before = len(self.lines)

        # Only copy Text objects (mutable), other renderables are typically immutable
        stored_content = content.copy() if isinstance(content, Text) else content

        result = super().write(content, width, expand, shrink, scroll_end, animate)

        # Store entry for re-rendering
        self._renderable_entries.append(RenderableEntry(
            renderable=stored_content,
            line_start=lines_before,
            line_count=len(self.lines) - lines_before
        ))

        # Track initial render width
        if not self._last_render_width and self.scrollable_content_region.width:
            self._last_render_width = self.scrollable_content_region.width

        return result

    def on_mount(self) -> None:
        if self.app:
            self._spinner_manager.app = self.app
            self._message_renderer.app = self.app
            self._tool_renderer.app = self.app
            self._scroll_controller.app = self.app
        return

    def on_unmount(self) -> None:
        self._scroll_controller.cleanup()
        self._tool_renderer.cleanup()
        self._spinner_manager.cleanup()
        # Clean up resize timer
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None

    def on_resize(self, event: Resize) -> None:
        """Handle terminal resize with debounced re-rendering."""
        super().on_resize(event)

        # Get new width from scrollable region
        new_width = self.scrollable_content_region.width
        if not new_width:
            return

        # Skip if width change is trivial
        if abs(new_width - self._last_render_width) < WIDTH_CHANGE_THRESHOLD:
            return

        # Cancel any pending resize timer
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None

        # Debounce: schedule re-render after delay
        self._resize_timer = self.set_timer(
            RESIZE_DEBOUNCE_MS / 1000,
            lambda: self._start_rerender(new_width)
        )

    def _start_rerender(self, new_width: int) -> None:
        """Start the incremental re-rendering process."""
        self._resize_timer = None

        if not self._renderable_entries:
            self._last_render_width = new_width
            return

        # Find first visible entry for scroll restoration
        first_visible_idx = self._find_first_visible_entry()

        # Capture spinner state before stopping
        spinner_state = self._capture_spinner_state()
        if spinner_state["active"]:
            self._spinner_manager._do_stop_spinner()

        # Clear lines and prepare for re-render
        self.lines.clear()
        if hasattr(self, "_line_cache"):
            self._line_cache.clear()
        self._widest_line_width = 0
        self._is_rerendering = True

        # Start batch re-rendering
        self._rerender_batch(0, new_width, first_visible_idx, spinner_state)

    def _rerender_batch(
        self,
        start_idx: int,
        new_width: int,
        first_visible_idx: int,
        spinner_state: dict,
    ) -> None:
        """Re-render a batch of entries, then schedule next batch."""
        entries = list(self._renderable_entries)
        end_idx = min(start_idx + RERENDER_BATCH_SIZE, len(entries))

        for i in range(start_idx, end_idx):
            entry = entries[i]
            lines_before = len(self.lines)
            # Re-render with shrink=True to fit new width
            super().write(entry.renderable, shrink=True, scroll_end=False)
            # Update entry's line tracking
            entry.line_start = lines_before
            entry.line_count = len(self.lines) - lines_before

        if end_idx < len(entries):
            # Schedule next batch to keep UI responsive
            self.call_later(
                lambda: self._rerender_batch(end_idx, new_width, first_visible_idx, spinner_state)
            )
        else:
            # All batches done, finalize
            self._finalize_rerender(new_width, first_visible_idx, spinner_state)

    def _finalize_rerender(
        self,
        new_width: int,
        first_visible_idx: int,
        spinner_state: dict,
    ) -> None:
        """Complete the re-render process and restore state."""
        self._is_rerendering = False
        self._last_render_width = new_width

        # Update virtual size
        self.virtual_size = Size(self._widest_line_width, len(self.lines))

        # Restore scroll position to first visible entry
        entries = list(self._renderable_entries)
        if 0 <= first_visible_idx < len(entries):
            entry = entries[first_visible_idx]
            self.scroll_to(y=entry.line_start, animate=False)
        elif self.auto_scroll:
            self.scroll_end(animate=False)

        # Restore spinner if it was active
        if spinner_state["active"]:
            msg = spinner_state["message"]
            if spinner_state["tip"]:
                msg = Text(f"{msg}\nTip: {spinner_state['tip']}")
            self._spinner_manager.start_spinner(msg)

        self.refresh()

    def _find_first_visible_entry(self) -> int:
        """Find index of first visible entry based on scroll position."""
        scroll_y = self.scroll_offset.y
        for i, entry in enumerate(self._renderable_entries):
            if entry.line_start + entry.line_count > scroll_y:
                return i
        # Default to last entry if at bottom
        return max(0, len(self._renderable_entries) - 1)

    def _capture_spinner_state(self) -> dict:
        """Capture current spinner state for restoration after re-render."""
        return {
            "active": self._spinner_manager._spinner_active,
            "message": self._spinner_manager._thinking_message,
            "tip": self._spinner_manager._thinking_tip,
        }

    def clear(self) -> "Self":
        """Clear all content including stored renderables."""
        self._renderable_entries.clear()
        self._protected_lines.clear()
        return super().clear()

    def set_debug_enabled(self, enabled: bool) -> None:
        """Enable or disable debug message display."""
        self._debug_enabled = enabled

    def add_debug_message(self, message: str, prefix: str = "DEBUG") -> None:
        """Add a debug message with gray/dimmed styling for execution flow visibility.

        Args:
            message: The debug message to display
            prefix: Optional prefix for categorizing debug messages (e.g., "QUERY", "TOOL", "AGENT")
        """
        if not self._debug_enabled:
            return
        debug_text = Text()
        debug_text.append(f"  [{prefix}] ", style=f"{SUBTLE} {CYAN}")
        debug_text.append(message, style=SUBTLE)
        self.write(debug_text)

        # Mark this line as protected from truncation
        line_idx = len(self.lines) - 1
        self._protected_lines.add(line_idx)

        # Prune old protected lines if we exceed the maximum
        self._prune_old_protected_lines()

    def _prune_old_protected_lines(self) -> None:
        """Remove oldest protected line indices if we exceed MAX_PROTECTED_LINES."""
        if len(self._protected_lines) > self.MAX_PROTECTED_LINES:
            sorted_lines = sorted(self._protected_lines)
            to_remove = len(self._protected_lines) - self.MAX_PROTECTED_LINES
            for idx in sorted_lines[:to_remove]:
                self._protected_lines.discard(idx)

    def _cleanup_protected_lines(self) -> None:
        """Remove protected lines that are out of bounds."""
        if not self._protected_lines:
            return
        
        # Filter out indices larger than current line count
        max_idx = len(self.lines) - 1
        valid_lines = {idx for idx in self._protected_lines if idx <= max_idx}
        
        if len(valid_lines) != len(self._protected_lines):
            self._protected_lines = valid_lines

    async def on_key(self, event) -> None:
        """Forward key events to scroll controller."""
        self._scroll_controller.on_key(event)

    def scroll_partial_page(self, direction: int) -> None:
        """Scroll a fraction of the viewport.
        
        Args:
           direction: -1 for up, 1 for down
        """
        self._scroll_controller.scroll_partial_page(direction)

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        self._scroll_controller.on_mouse_scroll_down(event)

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        self._scroll_controller.on_mouse_scroll_up(event)
    
    def on_mouse_down(self, event: MouseDown) -> None:
        self._scroll_controller.on_mouse_down(event)

    def on_mouse_move(self, event: MouseMove) -> None:
        self._scroll_controller.on_mouse_move(event)
    def on_mouse_up(self, event: MouseUp) -> None:
        self._scroll_controller.on_mouse_up(event)

    def add_user_message(self, message: str) -> None:
        self._message_renderer.add_user_message(message)

    def add_assistant_message(self, message: str) -> None:
        self._message_renderer.add_assistant_message(message)

    def add_system_message(self, message: str) -> None:
        self._message_renderer.add_system_message(message)

    def add_thinking_block(self, content: str) -> None:
        """Display thinking content with dark gray styling.

        Renders model reasoning from the think tool.

        Args:
            content: The thinking/reasoning content from the model
        """
        self._message_renderer.add_thinking_block(content)

    def add_error(self, message: str) -> None:
        """Render an error message with a red bullet and clear any active spinner."""
        self.stop_spinner()  # Retain state change logic here
        self._message_renderer.add_error(message)

    def render_approval_prompt(self, renderables: list[Any]) -> None:
        """Render the approval prompt panel."""
        # Clear existing if any
        if self._approval_start is not None:
            self.clear_approval_prompt()

        self._approval_start = len(self.lines)

        # Don't store approval content - it's temporary and will be cleared
        self._skip_renderable_storage = True
        for renderable in renderables:
            self.write(renderable)
        self._skip_renderable_storage = False

    def clear_approval_prompt(self) -> None:
        """Remove the approval prompt from the log."""
        if self._approval_start is None:
            return

        if self._approval_start < len(self.lines):
             del self.lines[self._approval_start:]
             self.refresh()
        
        self._approval_start = None

    def add_tool_call(self, display: Text | str, *_: Any) -> None:
        self._tool_renderer.add_tool_call(display)

    def start_tool_execution(self) -> None:
        self._tool_renderer.start_tool_execution()

    def stop_tool_execution(self, success: bool = True) -> None:
        self._tool_renderer.stop_tool_execution(success)

    def update_progress_text(self, message: str | Text) -> None:
        """Update the current progress/tool line text in-place."""
        self._tool_renderer.update_progress_text(message)

    def add_tool_result(self, result: str) -> None:
        self._tool_renderer.add_tool_result(result)

    def add_tool_result_continuation(self, lines: list[str]) -> None:
        """Add continuation lines for tool result (no ⎿ prefix, just space indentation)."""
        self._tool_renderer.add_tool_result_continuation(lines)

    def complete_nested_tool_call(
        self,
        tool_name: str,
        depth: int,
        parent: str,
        success: bool,
    ) -> None:
        self._tool_renderer.complete_nested_tool_call(tool_name, depth, parent, success)

    def add_nested_tree_result(
        self,
        tool_outputs: list[str],
        depth: int,
        is_last_parent: bool = True,
        has_error: bool = False,
        has_interrupted: bool = False,
    ) -> None:
        self._tool_renderer.add_nested_tree_result(
            tool_outputs, depth, is_last_parent, has_error, has_interrupted
        )

    def add_edit_diff_result(self, diff_text: str, depth: int, is_last_parent: bool = True) -> None:
        self._tool_renderer.add_edit_diff_result(diff_text, depth, is_last_parent)

    def add_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = ".",
        depth: int = 0,
    ) -> None:
        self._tool_renderer.add_bash_output_box(
            output, is_error, command, working_dir, depth
        )

    def start_streaming_bash_box(self, command: str = "", working_dir: str = ".") -> None:
        self._tool_renderer.start_streaming_bash_box(command, working_dir)

    def append_to_streaming_box(self, line: str, is_stderr: bool = False) -> None:
        self._tool_renderer.append_to_streaming_box(line, is_stderr)

    def close_streaming_bash_box(self, is_error: bool, exit_code: int) -> None:
        self._tool_renderer.close_streaming_bash_box(is_error, exit_code)

    def add_nested_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = "",
        depth: int = 1,
    ) -> None:
        self._tool_renderer.add_nested_bash_output_box(
             output, is_error, command, working_dir, depth
        )

    def add_nested_tool_call(
        self,
        display: Text | str,
        depth: int,
        parent: str,
    ) -> None:
        self._tool_renderer.add_nested_tool_call(display, depth, parent)

    def add_nested_tool_sub_results(self, lines: list, depth: int, is_last_parent: bool = True) -> None:
        """Add tool result lines for nested subagent tools."""
        self._tool_renderer.add_nested_tool_sub_results(lines, depth, is_last_parent)

    def add_todo_sub_result(self, text: str, depth: int, is_last_parent: bool = True) -> None:
        """Add a single sub-result line for todo operations."""
        self._tool_renderer.add_todo_sub_result(text, depth, is_last_parent)

    def add_todo_sub_results(self, items: list, depth: int, is_last_parent: bool = True) -> None:
        """Add multiple sub-result lines for todo list operations."""
        self._tool_renderer.add_todo_sub_results(items, depth, is_last_parent)

    def _truncate_from(self, index: int) -> None:
        if index >= len(self.lines):
            return

        # Check if any protected lines would be affected
        protected_in_range = [i for i in self._protected_lines if i >= index]
        if protected_in_range:
            # Don't truncate protected lines - find the first non-protected line after index
            # or skip truncation entirely if all lines after index are protected
            non_protected = [i for i in range(index, len(self.lines)) if i not in self._protected_lines]
            if not non_protected:
                return  # All lines after index are protected, skip truncation
            # Only delete non-protected lines
            for i in sorted(non_protected, reverse=True):
                if i < len(self.lines):
                    del self.lines[i]
        else:
            del self.lines[index:]

        if hasattr(self, '_line_cache'):
             self._line_cache.clear()

        # Update protected line indices after deletion
        new_protected = set()
        for p in self._protected_lines:
            if p < index:
                new_protected.add(p)
            elif p in protected_in_range:
                # Recalculate position - count how many non-protected lines before this were deleted
                deleted_before = len([i for i in range(index, p) if i not in self._protected_lines])
                new_protected.add(p - deleted_before)
        self._protected_lines = new_protected

        # Recalculate virtual size
        widths: List[int] = []
        for strip in self.lines:
            cell_length = getattr(strip, "cell_length", None)
            widths.append(cell_length() if callable(cell_length) else cell_length or 0)

        self._widest_line_width = max(widths, default=0)
        self._start_line = max(0, min(self._start_line, len(self.lines)))
        self.virtual_size = Size(self._widest_line_width, len(self.lines))

        if self.auto_scroll:
            self.scroll_end(animate=False)

        self.refresh()

    # --- Thinking Spinner handling ------------------------------------------------

    def start_spinner(self, message: Text | str) -> None:
        """Show thinking spinner (delegated to SpinnerManager)."""
        if self._debug_enabled:
             # Keep debug logging if useful, or move to manager?
             pass
        self._spinner_manager.start_spinner(message)

    def update_spinner(self, message: Text | str) -> None:
        """Update the thinking message."""
        self._spinner_manager.update_spinner(message)

    def stop_spinner(self) -> None:
        """Stop the thinking spinner."""
        self._spinner_manager.stop_spinner()

    def tick_spinner(self) -> None:
        """Advance spinner animation manually."""
        self._spinner_manager.tick_spinner()
