"""Widget-based conversation log for text selection support.

This module provides a new ConversationLog based on VerticalScroll
that mounts individual widgets for each message, enabling native
Textual text selection.

Key differences from RichLog-based approach:
- Uses VerticalScroll instead of RichLog
- Mounts message widgets instead of writing Text/Rich objects
- Each message widget supports text selection natively
- Maintains API compatibility with existing code through adapters
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from rich.text import Text
from textual.containers import VerticalScroll
from textual.events import MouseScrollDown, MouseScrollUp, Resize
from textual.widgets import Static

from swecli.ui_textual.style_tokens import SUBTLE, CYAN, ERROR, PRIMARY
from swecli.ui_textual.widgets.messages import (
    AssistantMessage,
    BashOutputMessage,
    ErrorMessage,
    NoMarkupStatic,
    NonSelectableStatic,
    SpinnerWidget,
    SystemMessage,
    ThinkingMessage,
    ToolCallMessage,
    ToolResultMessage,
    UserMessage,
)

if TYPE_CHECKING:
    from typing_extensions import Self


class ConversationLogV2(VerticalScroll):
    """VerticalScroll-based conversation log with text selection support.

    This is the new widget-based architecture that enables proper text selection.
    Each message is a mounted widget that can be selected independently.
    """

    can_focus = True
    ALLOW_SELECT = True

    DEFAULT_CSS = """
    ConversationLogV2 {
        width: 100%;
        height: 100%;
        scrollbar-gutter: stable;
    }

    ConversationLogV2 > * {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._auto_scroll = True
        self._user_scrolled = False
        self._spinner_active = False
        self._spinner_widget: SpinnerWidget | None = None
        self._current_assistant_widget: AssistantMessage | None = None
        self._current_thinking_widget: ThinkingMessage | None = None
        self._current_tool_widget: ToolCallMessage | None = None
        self._debug_enabled = False
        self._resize_timer: Any | None = None

    # --- Properties ---

    @property
    def auto_scroll(self) -> bool:
        return self._auto_scroll

    @auto_scroll.setter
    def auto_scroll(self, value: bool) -> None:
        self._auto_scroll = value

    # --- Lifecycle ---

    def on_mount(self) -> None:
        """Initialize on mount."""
        pass

    def on_unmount(self) -> None:
        """Cleanup on unmount."""
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None

    def on_resize(self, event: Resize) -> None:
        """Handle resize events."""
        # Widgets will automatically reflow with new width
        pass

    # --- Scrolling ---

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        """Handle mouse scroll down."""
        self._user_scrolled = True
        self._auto_scroll = False
        self.scroll_relative(y=3)
        event.stop()

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        """Handle mouse scroll up."""
        self._user_scrolled = True
        self._auto_scroll = False
        self.scroll_relative(y=-3)
        event.stop()

    def scroll_to_end(self, animate: bool = True) -> None:
        """Scroll to the bottom if auto-scroll is active."""
        if self._auto_scroll and not self._user_scrolled:
            self.scroll_end(animate=animate)

    # --- User Messages ---

    def add_user_message(self, message: str) -> None:
        """Add a user message widget."""
        widget = UserMessage(message)
        self.mount(widget)
        if self._auto_scroll:
            widget.scroll_visible()

    # --- Assistant Messages ---

    def add_assistant_message(self, message: str) -> None:
        """Add an assistant message widget.

        For non-streaming responses, pass the full message.
        For streaming, call start_assistant_streaming() instead.
        """
        widget = AssistantMessage(message)
        self.mount(widget)
        self._current_assistant_widget = widget
        if self._auto_scroll:
            widget.scroll_visible()
        # Write initial content
        self.call_later(widget.write_initial_content)

    def start_assistant_streaming(self) -> None:
        """Start a new streaming assistant message."""
        widget = AssistantMessage("")
        self.mount(widget)
        self._current_assistant_widget = widget
        if self._auto_scroll:
            widget.scroll_visible()

    async def append_assistant_content(self, content: str) -> None:
        """Append content to the current streaming assistant message."""
        if self._current_assistant_widget:
            await self._current_assistant_widget.append_content(content)
            if self._auto_scroll:
                self._current_assistant_widget.scroll_visible()

    async def finish_assistant_streaming(self) -> None:
        """Finish the current streaming assistant message."""
        if self._current_assistant_widget:
            await self._current_assistant_widget.stop_stream()
            self._current_assistant_widget = None

    # --- System Messages ---

    def add_system_message(self, message: str) -> None:
        """Add a system message widget."""
        widget = SystemMessage(message)
        self.mount(widget)
        if self._auto_scroll:
            widget.scroll_visible()

    # --- Error Messages ---

    def add_error(self, message: str) -> None:
        """Add an error message widget."""
        self.stop_spinner()  # Stop any active spinner
        widget = ErrorMessage(message)
        self.mount(widget)
        if self._auto_scroll:
            widget.scroll_visible()

    # --- Thinking/Reasoning ---

    def add_thinking_block(self, content: str) -> None:
        """Add a thinking block widget."""
        widget = ThinkingMessage(content, collapsed=True)
        self.mount(widget)
        self._current_thinking_widget = widget
        if self._auto_scroll:
            widget.scroll_visible()
        # Write initial content
        self.call_later(widget.write_initial_content)

    def start_thinking_streaming(self) -> None:
        """Start a new streaming thinking block."""
        widget = ThinkingMessage("", collapsed=True)
        self.mount(widget)
        self._current_thinking_widget = widget
        if self._auto_scroll:
            widget.scroll_visible()

    async def append_thinking_content(self, content: str) -> None:
        """Append content to the current thinking block."""
        if self._current_thinking_widget:
            await self._current_thinking_widget.append_content(content)

    def finish_thinking_streaming(self) -> None:
        """Finish the current thinking block."""
        if self._current_thinking_widget:
            self._current_thinking_widget.set_completed()
            self._current_thinking_widget = None

    # --- Tool Calls ---

    def add_tool_call(self, display: Text | str, *_: Any) -> None:
        """Add a tool call widget."""
        if isinstance(display, Text):
            tool_name = display.plain
        else:
            tool_name = str(display)

        widget = ToolCallMessage(tool_name)
        self.mount(widget)
        self._current_tool_widget = widget
        if self._auto_scroll:
            widget.scroll_visible()

    def start_tool_execution(self) -> None:
        """Mark the current tool as running."""
        if self._current_tool_widget:
            self._current_tool_widget.set_running()

    def stop_tool_execution(self, success: bool = True) -> None:
        """Mark the current tool as completed."""
        if self._current_tool_widget:
            if success:
                self._current_tool_widget.set_success()
            else:
                self._current_tool_widget.set_error()
            self._current_tool_widget = None

    def update_progress_text(self, message: str | Text) -> None:
        """Update the current tool's progress text."""
        # For now, just update the tool call if one exists
        if not self._current_tool_widget:
            if isinstance(message, Text):
                tool_name = message.plain
            else:
                tool_name = str(message)
            self.add_tool_call(tool_name)
            self.start_tool_execution()

    def add_tool_result(self, result: str) -> None:
        """Add a tool result widget."""
        widget = ToolResultMessage(result)
        self.mount(widget)
        if self._auto_scroll:
            widget.scroll_visible()

    def add_tool_result_continuation(self, lines: list[str]) -> None:
        """Add continuation lines for tool results."""
        for line in lines:
            widget = ToolResultMessage(line, show_prefix=False)
            self.mount(widget)
        if self._auto_scroll:
            self.scroll_end(animate=False)

    # --- Bash Output ---

    # Constants for output truncation (match original tool_renderer)
    MAIN_AGENT_HEAD_LINES = 50
    MAIN_AGENT_TAIL_LINES = 20
    SUBAGENT_HEAD_LINES = 15
    SUBAGENT_TAIL_LINES = 5
    GREY = "#7a7e86"
    ERROR_COLOR = "#ff5c57"
    SUBTLE = "#9aa0ac"

    def add_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = ".",
        depth: int = 0,
    ) -> None:
        """Add bash output matching original format with ⎿ prefix."""
        lines = output.rstrip("\n").splitlines()

        # Apply truncation based on depth
        if depth == 0:
            head_count = self.MAIN_AGENT_HEAD_LINES
            tail_count = self.MAIN_AGENT_TAIL_LINES
        else:
            head_count = self.SUBAGENT_HEAD_LINES
            tail_count = self.SUBAGENT_TAIL_LINES

        head_lines, tail_lines, hidden_count = self._truncate_lines(
            lines, head_count, tail_count
        )

        indent = "  " * depth

        # Output lines with ⎿ prefix for first line, spaces for rest
        is_first = True
        for line in head_lines:
            self._write_bash_line(line, indent, is_error, is_first)
            is_first = False

        if hidden_count > 0:
            hidden_text = Text(f"{indent}       ... {hidden_count} lines hidden ...", style=f"{self.SUBTLE} italic")
            self.write(hidden_text)

        for line in tail_lines:
            self._write_bash_line(line, indent, is_error, is_first)
            is_first = False

    def _truncate_lines(self, lines: list, head: int, tail: int) -> tuple:
        """Truncate lines to head + tail, returning (head_lines, tail_lines, hidden_count)."""
        total = len(lines)
        if total <= head + tail:
            return lines, [], 0
        return lines[:head], lines[-tail:], total - head - tail

    def _write_bash_line(self, line: str, indent: str, is_error: bool, is_first: bool) -> None:
        """Write a single bash output line with proper formatting."""
        # Normalize line (remove control characters)
        normalized = ''.join(c for c in line if c >= ' ' or c in '\t\n')
        # Use ⎿ prefix for first line, spaces for rest
        prefix = f"{indent}  ⎿  " if is_first else f"{indent}       "
        output_line = Text(prefix, style=self.GREY)
        output_line.append(normalized, style=self.ERROR_COLOR if is_error else self.GREY)
        self.write(output_line)

    def start_streaming_bash_box(self, command: str = "", working_dir: str = ".") -> None:
        """Start a streaming bash output (stub for compatibility)."""
        pass

    def append_to_streaming_box(self, line: str, is_stderr: bool = False) -> None:
        """Append to streaming bash output."""
        output_line = Text("       ", style=self.GREY)
        output_line.append(line, style=self.ERROR_COLOR if is_stderr else self.GREY)
        self.write(output_line)

    def close_streaming_bash_box(self, is_error: bool, exit_code: int) -> None:
        """Close streaming bash output (stub for compatibility)."""
        pass

    def add_nested_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = "",
        depth: int = 1,
    ) -> None:
        """Add a nested bash output widget."""
        self.add_bash_output_box(output, is_error, command, working_dir, depth)

    # --- Nested Tool Calls ---

    def add_nested_tool_call(
        self,
        display: Text | str,
        depth: int,
        parent: str,
    ) -> None:
        """Add a nested tool call widget."""
        if isinstance(display, Text):
            tool_name = display.plain
        else:
            tool_name = str(display)
        widget = ToolCallMessage(tool_name)
        self.mount(widget)
        if self._auto_scroll:
            widget.scroll_visible()

    def complete_nested_tool_call(
        self,
        tool_name: str,
        depth: int,
        parent: str,
        success: bool,
    ) -> None:
        """Complete a nested tool call (stub for compatibility)."""
        pass

    def add_nested_tree_result(
        self,
        tool_outputs: list[str],
        depth: int,
        is_last_parent: bool = True,
        has_error: bool = False,
        has_interrupted: bool = False,
    ) -> None:
        """Add nested tree result lines."""
        for line in tool_outputs:
            widget = ToolResultMessage(line, show_prefix=False)
            self.mount(widget)

    def add_edit_diff_result(
        self, diff_text: str, depth: int, is_last_parent: bool = True
    ) -> None:
        """Add edit diff result lines."""
        for line in diff_text.split('\n'):
            widget = ToolResultMessage(line, show_prefix=False)
            self.mount(widget)

    def add_nested_tool_sub_results(
        self, lines: list, depth: int, is_last_parent: bool = True
    ) -> None:
        """Add nested tool sub-results."""
        for line in lines:
            widget = ToolResultMessage(str(line), show_prefix=False)
            self.mount(widget)

    def add_todo_sub_result(
        self, text: str, depth: int, is_last_parent: bool = True
    ) -> None:
        """Add a todo sub-result line."""
        widget = ToolResultMessage(text, show_prefix=False)
        self.mount(widget)

    def add_todo_sub_results(
        self, items: list, depth: int, is_last_parent: bool = True
    ) -> None:
        """Add todo sub-result items."""
        for symbol, title in items:
            widget = ToolResultMessage(f"{symbol} {title}", show_prefix=False)
            self.mount(widget)

    # --- Spinner ---

    def start_spinner(self, message: Text | str) -> None:
        """Show a thinking spinner with animation."""
        import re

        if self._spinner_active and self._spinner_widget:
            self.update_spinner(message)
            return

        self._spinner_active = True

        # Parse message and tip
        if isinstance(message, Text):
            plain = message.plain
        else:
            plain = str(message)

        tip = ""
        if "\n" in plain:
            parts = plain.split("\n", 1)
            text = parts[0].strip()
            if len(parts) > 1 and "Tip:" in parts[1]:
                tip_match = re.search(r'Tip:\s*(.+)', parts[1])
                if tip_match:
                    tip = tip_match.group(1).strip()
        else:
            text = plain.strip()

        self._spinner_widget = SpinnerWidget(message=text, tip=tip, classes="spinner-widget")
        self.mount(self._spinner_widget)
        if self._auto_scroll:
            self._spinner_widget.scroll_visible()

    def update_spinner(self, message: Text | str) -> None:
        """Update the thinking message."""
        import re

        if not self._spinner_widget:
            self.start_spinner(message)
            return

        # Parse message and tip
        if isinstance(message, Text):
            plain = message.plain
        else:
            plain = str(message)

        tip = ""
        if "\n" in plain:
            parts = plain.split("\n", 1)
            text = parts[0].strip()
            if len(parts) > 1 and "Tip:" in parts[1]:
                tip_match = re.search(r'Tip:\s*(.+)', parts[1])
                if tip_match:
                    tip = tip_match.group(1).strip()
        else:
            text = plain.strip()

        self._spinner_widget.update_message(text, tip)

    def stop_spinner(self) -> None:
        """Stop the thinking spinner."""
        self._spinner_active = False
        if self._spinner_widget:
            self._spinner_widget.remove()
            self._spinner_widget = None

    def tick_spinner(self) -> None:
        """Advance spinner animation (handled automatically by SpinnerWidget)."""
        pass

    # --- Approval Prompts ---

    def render_approval_prompt(self, renderables: list[Any]) -> None:
        """Render approval prompt with Rich renderables (Panel, Text, etc)."""
        for renderable in renderables:
            # Use Static which accepts Rich renderables directly
            widget = Static(renderable)
            widget.add_class("approval-prompt")
            self.mount(widget)
        if self._auto_scroll:
            self.scroll_end(animate=False)

    def clear_approval_prompt(self) -> None:
        """Clear approval prompt widgets."""
        for widget in self.query(".approval-prompt"):
            widget.remove()

    def defer_approval_clear(self) -> None:
        """Mark approval for deferred clearing."""
        pass  # Will be cleared on next action

    # --- Debug ---

    def set_debug_enabled(self, enabled: bool) -> None:
        """Enable or disable debug messages."""
        self._debug_enabled = enabled

    def add_debug_message(self, message: str, prefix: str = "DEBUG") -> None:
        """Add a debug message."""
        if not self._debug_enabled:
            return
        debug_text = f"[{prefix}] {message}"
        widget = NoMarkupStatic(debug_text, classes="debug-message")
        self.mount(widget)

    # --- Compatibility Methods ---

    def write(
        self,
        content: Any,
        width: int | None = None,
        expand: bool = False,
        shrink: bool = True,
        scroll_end: bool | None = None,
        animate: bool = False,
    ) -> "Self":
        """Compatibility method for RichLog-style write().

        Converts Rich renderables to Static widgets for mounting.
        Static widgets can accept Rich Text objects directly and preserve styling.
        Skips empty content to avoid creating widgets that take up vertical space.
        """
        # Skip empty content - don't create widgets for blank lines
        # In RichLog, write(Text("")) adds a blank line, but here it would create
        # a widget that takes up space even when empty
        if isinstance(content, Text):
            if not content.plain.strip():
                return self  # Skip empty Text objects
            widget = Static(content)  # Static accepts Rich Text directly!
        elif hasattr(content, '__rich__') or hasattr(content, '__rich_console__'):
            # Other Rich renderables (Panel, Syntax, etc.) - don't skip these
            widget = Static(content)
        else:
            text_content = str(content)
            if not text_content.strip():
                return self  # Skip empty strings
            widget = NoMarkupStatic(text_content)

        # Remove margin for write() calls - they're inline content, not message blocks
        widget.styles.margin = (0, 0, 0, 0)
        widget.styles.padding = (0, 0, 0, 0)
        widget.styles.height = "auto"

        # Enable text selection on this widget
        widget.can_focus = True
        widget.ALLOW_SELECT = True

        self.mount(widget)

        if scroll_end or (scroll_end is None and self._auto_scroll):
            widget.scroll_visible()

        return self

    def refresh_line(self, y: int) -> None:
        """Compatibility stub - widgets refresh themselves."""
        self.refresh()

    @property
    def lines(self) -> list:
        """Compatibility property - returns empty list.

        The new widget-based architecture doesn't use lines.
        This prevents AttributeError for code that checks lines.
        """
        return []

    def scroll_partial_page(self, direction: int) -> None:
        """Scroll a fraction of the viewport."""
        height = self.size.height
        stride = max(height // 10, 3)
        self.scroll_relative(y=direction * stride)

    # --- Clear ---

    def clear(self) -> "Self":
        """Clear all content."""
        for child in list(self.children):
            child.remove()
        return self
