"""Conversation log widget with markdown-aware rendering and tool formatting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.events import MouseDown, MouseMove, MouseScrollDown, MouseScrollUp, MouseUp, Resize
from textual.geometry import Size
from textual.strip import Strip
from textual.timer import Timer
from textual.widgets import RichLog
from swecli.ui_textual.style_tokens import SUBTLE, CYAN

if TYPE_CHECKING:
    from typing_extensions import Self

from swecli.ui_textual.widgets.conversation.spinner_manager import DefaultSpinnerManager
from swecli.ui_textual.widgets.conversation.message_renderer import DefaultMessageRenderer
from swecli.ui_textual.widgets.conversation.tool_renderer import DefaultToolRenderer
from swecli.ui_textual.widgets.conversation.scroll_controller import DefaultScrollController


@dataclass
class LineSource:
    """Tracks the source renderable for a line for resize re-rendering."""

    source: RenderableType  # Original Rich renderable
    wrap: bool  # Whether this content should wrap on resize
    line_indices: list[int] = field(default_factory=list)  # Line indices this source maps to


class ConversationLog(RichLog):
    """Enhanced RichLog for conversation display with scrolling support."""

    can_focus = True
    ALLOW_SELECT = True

    # Maximum number of line sources to track (memory cap)
    MAX_LINE_SOURCES = 2000

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
        self._ask_user_start: int | None = None
        self._debug_enabled = False  # Enable debug messages by default
        self._protected_lines: set[int] = set()  # Lines that should not be truncated
        self.MAX_PROTECTED_LINES = 200

        # Source tracking for resize re-rendering
        self._line_sources: list[LineSource] = []
        self._last_render_width: int = 0
        self._resize_timer: Optional[Timer] = None
        
    def refresh_line(self, y: int) -> None:
        """Refresh a specific line by invalidating cache and repainting."""
        # Aggressively clear cache to ensure spinner animation updates
        if hasattr(self, '_line_cache'):
            self._line_cache.clear()
        self.refresh()

    def write(
        self,
        content: RenderableType,
        width: int | None = None,
        expand: bool = False,
        shrink: bool = True,
        scroll_end: bool | None = None,
        animate: bool = False,
        wrap: bool | None = None,
    ) -> "Self":
        """Write content, storing source for potential re-rendering on resize.

        Args:
            content: Rich renderable to write
            width: Optional width override
            expand: Whether to expand to container width
            shrink: Whether to shrink to fit content
            scroll_end: Whether to scroll to end after write
            animate: Whether to animate scroll
            wrap: Whether this content should re-wrap on resize.
                  If None, uses self.wrap (True by default).
                  Pass False for fixed-width content (terminal boxes, diffs, spinners).

        Returns:
            Self for chaining
        """
        # Determine if this content should wrap (default from self.wrap)
        should_wrap = wrap if wrap is not None else self.wrap

        # Track line count before write to map source to lines
        lines_before = len(self.lines)

        # Call parent write
        result = super().write(
            content,
            width=width,
            expand=expand,
            shrink=shrink,
            scroll_end=scroll_end,
            animate=animate,
        )

        # Track line count after write
        lines_after = len(self.lines)

        # Store source for re-rendering (only for wrappable content)
        if should_wrap:
            line_indices = list(range(lines_before, lines_after))
            self._line_sources.append(
                LineSource(source=content, wrap=True, line_indices=line_indices)
            )
            # Prune old sources if we exceed the memory cap
            self._prune_old_line_sources()
        else:
            # For non-wrappable content, store None source to maintain index mapping
            line_indices = list(range(lines_before, lines_after))
            self._line_sources.append(
                LineSource(source=content, wrap=False, line_indices=line_indices)
            )
            self._prune_old_line_sources()

        return result

    def _prune_old_line_sources(self) -> None:
        """Remove oldest line sources if we exceed MAX_LINE_SOURCES."""
        if len(self._line_sources) > self.MAX_LINE_SOURCES:
            # Remove oldest sources
            to_remove = len(self._line_sources) - self.MAX_LINE_SOURCES
            self._line_sources = self._line_sources[to_remove:]

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
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None

    def on_resize(self, event: Resize) -> None:
        """Handle terminal resize by re-rendering wrappable content.

        Unlike the default RichLog behavior which just clears caches,
        we actually re-render stored source renderables at the new width
        to properly reflow text content.
        """
        super().on_resize(event)

        # Get new content width
        new_width = self.scrollable_content_region.width

        # Only re-render if width actually changed and is valid
        if new_width != self._last_render_width and new_width > 0:
            self._last_render_width = new_width
            self._schedule_rerender()

    def _schedule_rerender(self) -> None:
        """Schedule a debounced re-render to avoid excessive re-rendering during rapid resize."""
        if self._resize_timer is not None:
            self._resize_timer.stop()
        # Debounce: wait 100ms before re-rendering
        self._resize_timer = self.set_timer(0.1, self._rerender_wrappable_content)

    def _rerender_wrappable_content(self) -> None:
        """Re-render all wrappable content at current width."""
        self._resize_timer = None

        width = self.scrollable_content_region.width
        if width <= 0:
            return

        # Create console at new width for rendering
        console = Console(width=width, force_terminal=True, no_color=False)

        # Track which lines we've updated to avoid duplicates
        updated_lines: set[int] = set()

        for source_entry in self._line_sources:
            if not source_entry.wrap:
                # Skip non-wrappable content (terminal boxes, diffs, etc.)
                continue

            if not source_entry.line_indices:
                continue

            # Get the first line index for this source
            first_line_idx = source_entry.line_indices[0]
            if first_line_idx in updated_lines:
                continue

            # Check if line indices are still valid
            if first_line_idx >= len(self.lines):
                continue

            # Re-render the source at new width
            try:
                # Render to segments using the console at new width
                segments = list(console.render(source_entry.source))
                new_strip = Strip(segments)

                # Update the line in place
                # Note: If the content wraps to multiple lines now, we only update the first
                # This is a simplification - full multi-line handling would be more complex
                self.lines[first_line_idx] = new_strip
                updated_lines.add(first_line_idx)
            except Exception:
                # If rendering fails, leave the line as-is
                pass

        # Clear cache and refresh
        if hasattr(self, "_line_cache"):
            self._line_cache.clear()
        self.refresh()

    def clear(self) -> "Self":
        """Clear all content."""
        self._protected_lines.clear()
        self._line_sources.clear()
        self._last_render_width = 0
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

    def add_command_result(self, lines: list[str], is_error: bool = False) -> None:
        """Render command result lines with tree continuation prefix.

        Used for displaying results from slash commands. Uses the same tree
        prefix (⎿) as tool results for visual consistency.

        Args:
            lines: List of result lines to display
            is_error: If True, use error styling; otherwise use subtle styling
        """
        self._message_renderer.add_command_result(lines, is_error)

    def render_approval_prompt(self, renderables: list[Any]) -> None:
        """Render the approval prompt panel."""
        # Clear existing if any
        if self._approval_start is not None:
            self.clear_approval_prompt()

        self._approval_start = len(self.lines)

        for renderable in renderables:
            self.write(renderable)

    def clear_approval_prompt(self) -> None:
        """Remove the approval prompt from the log."""
        if self._approval_start is None:
            return

        if self._approval_start < len(self.lines):
             del self.lines[self._approval_start:]
             self.refresh()

        self._approval_start = None

    def render_ask_user_prompt(self, renderables: list[Any]) -> None:
        """Render the ask-user prompt panel.

        Args:
            renderables: List of Rich renderables to display
        """
        # Clear existing if any
        if self._ask_user_start is not None:
            self.clear_ask_user_prompt()

        self._ask_user_start = len(self.lines)

        for renderable in renderables:
            self.write(renderable)

    def clear_ask_user_prompt(self) -> None:
        """Remove the ask-user prompt from the log."""
        if self._ask_user_start is None:
            return

        if self._ask_user_start < len(self.lines):
            del self.lines[self._ask_user_start:]
            self.refresh()

        self._ask_user_start = None

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
        tool_id: str = "",
    ) -> None:
        self._tool_renderer.complete_nested_tool_call(tool_name, depth, parent, success, tool_id)

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
        tool_id: str = "",
    ) -> None:
        self._tool_renderer.add_nested_tool_call(display, depth, parent, tool_id)

    def add_nested_tool_sub_results(self, lines: list, depth: int, is_last_parent: bool = True) -> None:
        """Add tool result lines for nested subagent tools."""
        self._tool_renderer.add_nested_tool_sub_results(lines, depth, is_last_parent)

    def add_todo_sub_result(self, text: str, depth: int, is_last_parent: bool = True) -> None:
        """Add a single sub-result line for todo operations."""
        self._tool_renderer.add_todo_sub_result(text, depth, is_last_parent)

    def add_todo_sub_results(self, items: list, depth: int, is_last_parent: bool = True) -> None:
        """Add multiple sub-result lines for todo list operations."""
        self._tool_renderer.add_todo_sub_results(items, depth, is_last_parent)

    # --- Parallel Agent Group Methods ---

    def on_parallel_agents_start(self, agent_infos: list[dict] | list[str]) -> None:
        """Called when parallel agents start executing.

        Args:
            agent_infos: List of agent info dicts with keys (new format):
                - agent_type: Type of agent (e.g., "Explore")
                - description: Short description of agent's task
                - tool_call_id: Unique ID for tracking this agent
                Or list of agent name strings (legacy format for backward compatibility).
        """
        # Convert legacy string format to dict format
        if agent_infos and isinstance(agent_infos[0], str):
            agent_infos = [
                {"agent_type": name, "description": name, "tool_call_id": name}
                for name in agent_infos
            ]
        self._tool_renderer.on_parallel_agents_start(agent_infos)

    def on_parallel_agent_complete(self, agent_name: str, success: bool) -> None:
        """Called when a parallel agent completes."""
        self._tool_renderer.on_parallel_agent_complete(agent_name, success)

    def on_parallel_agents_done(self) -> None:
        """Called when all parallel agents have completed."""
        self._tool_renderer.on_parallel_agents_done()

    # --- Single Agent Methods (treated as parallel group of 1) ---

    def on_single_agent_start(self, agent_type: str, description: str, tool_call_id: str) -> None:
        """Called when a single agent starts (non-parallel execution).

        Args:
            agent_type: Type of agent (e.g., "Explore", "Code-Explorer")
            description: Task description
            tool_call_id: Unique ID for tracking
        """
        self._tool_renderer.on_single_agent_start(agent_type, description, tool_call_id)

    def on_single_agent_complete(self, tool_call_id: str, success: bool = True) -> None:
        """Called when a single agent completes.

        Args:
            tool_call_id: Unique ID of the agent that completed
            success: Whether the agent succeeded
        """
        self._tool_renderer.on_single_agent_complete(tool_call_id, success)

    def toggle_parallel_expansion(self) -> bool:
        """Toggle expand/collapse state of parallel agent display."""
        return self._tool_renderer.toggle_parallel_expansion()

    def has_active_parallel_group(self) -> bool:
        """Check if there's an active parallel agent group."""
        return self._tool_renderer.has_active_parallel_group()

    # --- Collapsible Output Methods ---

    def toggle_output_expansion(self) -> bool:
        """Toggle the most recent collapsible output region.

        Returns:
            True if a region was toggled, False if none found.
        """
        return self._tool_renderer.toggle_most_recent_collapsible()

    def has_collapsible_output(self) -> bool:
        """Check if there are any collapsible output regions.

        Returns:
            True if at least one collapsible region exists.
        """
        return self._tool_renderer.has_collapsible_output()

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
