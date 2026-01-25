"""Conversation log widget with markdown-aware rendering and tool formatting."""

from __future__ import annotations

from typing import Any, List, Optional, TYPE_CHECKING

from rich.console import Console, RenderableType
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
from swecli.ui_textual.widgets.conversation.block_registry import BlockRegistry, ContentBlock


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
        self._ask_user_start: int | None = None
        self._debug_enabled = False  # Enable debug messages by default
        self._protected_lines: set[int] = set()  # Lines that should not be truncated
        self.MAX_PROTECTED_LINES = 200

        # Block-based tracking for resize re-rendering
        self._block_registry = BlockRegistry()
        self._last_render_width: int = 0
        self._resize_timer: Optional[Timer] = None

    def refresh_line(self, y: int) -> None:
        """Refresh a specific line by invalidating cache and repainting."""
        # Aggressively clear cache to ensure spinner animation updates
        if hasattr(self, "_line_cache"):
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
        wrappable: bool = True,
    ) -> "Self":
        """Write content, registering as a block for resize handling.

        Args:
            content: Rich renderable to write
            width: Optional width override
            expand: Whether to expand to container width
            shrink: Whether to shrink to fit content
            scroll_end: Whether to scroll to end after write
            animate: Whether to animate scroll
            wrappable: Whether this content should re-wrap on resize.
                       Defaults to True for prose text.
                       Pass False for fixed-width content (terminal boxes, diffs, spinners).

        Returns:
            Self for chaining
        """
        import uuid

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

        lines_after = len(self.lines)

        # Register this write as a content block
        block = ContentBlock(
            block_id=str(uuid.uuid4()),
            source=content,
            is_wrappable=wrappable,
            start_line=lines_before,
            line_count=lines_after - lines_before,
        )
        self._block_registry.register(block)

        return result

    def lock_block(self, block_id: str) -> None:
        """Lock a block to prevent re-rendering during animation.

        Args:
            block_id: Unique identifier of the block to lock
        """
        self._block_registry.lock_block(block_id)

    def unlock_block(self, block_id: str) -> None:
        """Unlock a block to allow re-rendering.

        Args:
            block_id: Unique identifier of the block to unlock
        """
        self._block_registry.unlock_block(block_id)

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
        """Handle terminal resize by re-rendering wrappable blocks.

        Uses the BlockRegistry to track which content blocks should be
        re-rendered at the new width.
        """
        super().on_resize(event)

        # Get new content width
        new_width = self.scrollable_content_region.width

        # Skip if width is invalid
        if new_width <= 0:
            return

        # On first resize (startup), just record the width without re-rendering
        # since content was just rendered at this width
        if self._last_render_width == 0:
            self._last_render_width = new_width
            return

        # Only re-render if width actually changed
        if new_width != self._last_render_width:
            self._last_render_width = new_width
            self._schedule_rerender()

    def _schedule_rerender(self) -> None:
        """Schedule a debounced re-render to avoid excessive re-rendering during rapid resize."""
        if self._resize_timer is not None:
            self._resize_timer.stop()
        # Debounce: wait 100ms before re-rendering
        self._resize_timer = self.set_timer(0.1, self._rerender_blocks)

    def _has_active_line_tracking(self) -> bool:
        """Check if any component has active state that tracks line indices.

        When line indices are being actively tracked (spinners, tool calls, etc.),
        re-rendering would corrupt these indices and cause display issues.

        Returns:
            True if re-rendering should be skipped to avoid corruption
        """
        # Check spinner manager
        sm = self._spinner_manager
        if sm._spinner_active:
            return True
        if sm._spinner_start is not None:
            return True

        # Check tool renderer active states
        tr = self._tool_renderer

        # Active tool call
        if tr._tool_call_start is not None:
            return True

        # Active nested tools
        if tr._nested_tools:
            return True
        if tr._nested_tool_line is not None:
            return True

        # Active parallel agent group
        if tr._parallel_group is not None:
            return True

        # Active single agent
        if tr._single_agent is not None:
            return True

        # Active streaming bash box
        if tr._streaming_box_header_line is not None:
            return True

        # Active approval prompt
        if self._approval_start is not None:
            return True

        # Active ask-user prompt
        if self._ask_user_start is not None:
            return True

        return False

    def _rerender_blocks(self) -> None:
        """Re-render all wrappable, unlocked blocks at current width."""
        self._resize_timer = None

        # CRITICAL: Skip re-rendering if any component has active line tracking
        # to avoid corrupting stored line indices
        if self._has_active_line_tracking():
            return

        width = self.scrollable_content_region.width
        if width <= 0:
            return

        console = Console(width=width, force_terminal=True, no_color=False)

        # Process blocks in order, adjusting indices as we go
        cumulative_delta = 0
        for block in self._block_registry.get_all_blocks():
            if not block.is_wrappable or block.is_locked:
                # Just adjust for previous deltas
                block.start_line += cumulative_delta
                continue

            # Adjust start for previous deltas
            block.start_line += cumulative_delta

            # Re-render this block
            new_strips = self._render_source_to_strips(block.source, console)
            old_count = block.line_count
            new_count = len(new_strips)

            # Replace lines
            start = block.start_line
            if start < len(self.lines):
                # Delete old lines
                end = min(start + old_count, len(self.lines))
                del self.lines[start:end]
                # Insert new lines
                for i, strip in enumerate(new_strips):
                    self.lines.insert(start + i, strip)

            # Update block and track delta
            block.line_count = new_count
            delta = new_count - old_count
            cumulative_delta += delta

        # Clear cache and refresh
        if hasattr(self, "_line_cache"):
            self._line_cache.clear()
        self.refresh()

    def _render_source_to_strips(self, source: RenderableType, console: Console) -> list[Strip]:
        """Render a source renderable to Strip objects.

        Args:
            source: Rich renderable to render
            console: Console configured with target width

        Returns:
            List of Strip objects, one per line
        """
        from rich.segment import Segment

        # Render the source to segments
        segments = list(console.render(source))

        # Split segments into lines based on newlines
        strips: list[Strip] = []
        current_line_segments: list[Segment] = []

        for segment in segments:
            text = segment.text
            style = segment.style

            if "\n" in text:
                # Split on newlines
                parts = text.split("\n")
                for i, part in enumerate(parts):
                    if part:
                        current_line_segments.append(Segment(part, style))
                    if i < len(parts) - 1:
                        # End of line
                        strips.append(Strip(current_line_segments))
                        current_line_segments = []
            else:
                current_line_segments.append(segment)

        # Don't forget the last line if it doesn't end with newline
        if current_line_segments:
            strips.append(Strip(current_line_segments))

        # Ensure at least one strip
        if not strips:
            strips.append(Strip([]))

        return strips

    def clear(self) -> "Self":
        """Clear all content."""
        self._protected_lines.clear()
        self._block_registry.clear()
        self._last_render_width = 0
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None
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
            del self.lines[self._approval_start :]
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

        # Remove any trailing blank line to connect panel directly to spinner
        # The panel is part of tool execution flow, no spacing needed
        while self.lines:
            last_line = self.lines[-1]
            content = ""
            if hasattr(last_line, "plain"):
                content = last_line.plain.strip() if last_line.plain else ""
            elif hasattr(last_line, "text"):
                content = last_line.text.strip() if last_line.text else ""
            if not content:
                self.lines.pop()
            else:
                break

        self._ask_user_start = len(self.lines)

        for renderable in renderables:
            self.write(renderable)

    def clear_ask_user_prompt(self) -> None:
        """Remove the ask-user prompt from the log."""
        if self._ask_user_start is None:
            return

        if self._ask_user_start < len(self.lines):
            del self.lines[self._ask_user_start :]
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
        self._tool_renderer.add_bash_output_box(output, is_error, command, working_dir, depth)

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

    def add_nested_tool_sub_results(
        self, lines: list, depth: int, is_last_parent: bool = True
    ) -> None:
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
            non_protected = [
                i for i in range(index, len(self.lines)) if i not in self._protected_lines
            ]
            if not non_protected:
                return  # All lines after index are protected, skip truncation
            # Only delete non-protected lines
            for i in sorted(non_protected, reverse=True):
                if i < len(self.lines):
                    del self.lines[i]
        else:
            del self.lines[index:]

        if hasattr(self, "_line_cache"):
            self._line_cache.clear()

        # Remove blocks that start at or after the truncation point
        self._block_registry.remove_blocks_from(index)

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
