"""Conversation log widget with markdown-aware rendering and tool formatting."""

from __future__ import annotations

import re
import time
from typing import Any, List, Tuple

from rich.console import Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.events import MouseDown, MouseMove, MouseScrollDown, MouseScrollUp, MouseUp
from textual.geometry import Size
from textual.timer import Timer
from textual.widgets import RichLog

from swecli.ui_textual.renderers import render_markdown_text_segment
from swecli.ui_textual.constants import TOOL_ERROR_SENTINEL
from swecli.ui_textual.widgets.terminal_box_renderer import (
    TerminalBoxConfig,
    TerminalBoxRenderer,
)


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
        self._user_scrolled = False
        self._last_assistant_rendered: str | None = None
        self._spinner_start: int | None = None
        self._spinner_line_count = 0
        self._tool_spinner_timer: Timer | None = None
        self._tool_display: Text | None = None
        self._spinner_active = False
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._spinner_index = 0
        self._tool_call_start: int | None = None
        self._approval_start: int | None = None
        self._tool_timer_start: float | None = None
        self._tool_last_elapsed: int | None = None
        self._debug_enabled = True  # Enable debug messages by default
        self._protected_lines: set[int] = set()  # Lines that should not be truncated
        self.MAX_PROTECTED_LINES = 200
        # Nested tool call pulsing animation state
        self._nested_tool_line: int | None = None  # Line index of last nested tool call
        self._nested_tool_text: Text | None = None  # Original text for the nested tool
        self._nested_tool_depth: int = 1  # Depth for indentation
        self._nested_pulse_bright = True  # Toggle for dim/bright pulsing
        self._nested_pulse_counter = 0  # Counter to slow down pulse rate
        # Track if last written line has content (for blank line insertion logic)
        self._last_line_has_content = False
        # Streaming bash box state
        self._streaming_box_header_line: int | None = None  # Line index of header row
        self._streaming_box_width: int = 60  # Box width
        self._streaming_box_top_line: int | None = None  # Line index of top border (for error restyling)
        # Streaming box data storage (for rebuild on close)
        self._streaming_box_command: str = ""
        self._streaming_box_working_dir: str = "."
        self._streaming_box_content_lines: list[tuple[str, bool]] = []  # (line, is_stderr)
        self._streaming_box_config: TerminalBoxConfig | None = None  # Config for streaming box
        # Mouse drag detection for selection tip
        self._mouse_down_pos: tuple[int, int] | None = None
        # Terminal box renderer (unified rendering for main/subagent output)
        self._box_renderer = TerminalBoxRenderer(self._get_box_width)

    def write(self, content, *args, **kwargs) -> None:
        """Override write to track content state for spacing logic."""
        super().write(content, *args, **kwargs)
        # Track if this was a blank line or content
        if isinstance(content, Text):
            self._last_line_has_content = bool(content.plain.strip())
        else:
            self._last_line_has_content = bool(str(content).strip())

    def on_mount(self) -> None:
        return

    def on_unmount(self) -> None:
        if self._tool_spinner_timer is not None:
            self._tool_spinner_timer.stop()
            self._tool_spinner_timer = None

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
        debug_text.append(f"  [{prefix}] ", style="dim cyan")
        debug_text.append(message, style="dim")
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

    async def on_key(self, event) -> None:
        """Handle key events, delegating to overlays if active, else scrolling."""
        
        # Check for active overlays (Approval Prompt or Model Picker)
        app = getattr(self, "app", None)
        if app:
            # 1. Approval Prompt
            approval_controller = getattr(app, "_approval_controller", None)
            if approval_controller and getattr(approval_controller, "active", False):
                if event.key == "up":
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_approval_move"):
                        app._approval_move(-1)
                    return
                if event.key == "down":
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_approval_move"):
                        app._approval_move(1)
                    return
                if event.key in {"enter", "return"} and "+" not in event.key:
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_approval_confirm"):
                        app._approval_confirm()
                    return
                if event.key in {"escape", "ctrl+c"}:
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_approval_cancel"):
                        app._approval_cancel()
                    return
                return  # Swallow other keys in approval mode? Or let them pass?

            # 2. Model Picker
            model_picker = getattr(app, "_model_picker", None)
            if model_picker and getattr(model_picker, "active", False):
                if event.key == "up":
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_model_picker_move"):
                        app._model_picker_move(-1)
                    return
                if event.key == "down":
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_model_picker_move"):
                        app._model_picker_move(1)
                    return
                if event.key in {"enter", "return"} and "+" not in event.key:
                    event.stop()
                    event.prevent_default()
                    confirm = getattr(app, "_model_picker_confirm", None)
                    if confirm is not None:
                        result = confirm()
                        import inspect
                        if inspect.isawaitable(result):
                            await result
                    return
                if event.key in {"escape", "ctrl+c"}:
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_model_picker_cancel"):
                        app._model_picker_cancel()
                    return
                if event.character and event.character.lower() == "b":
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_model_picker_back"):
                        app._model_picker_back()
                    return

        # Default scrolling behavior
        # Handle Page Up/Down (or Fn+Up/Down) with a smaller stride for finer control
        if event.key == "pageup":
            self.scroll_partial_page(direction=-1)
            event.prevent_default()
            return

        elif event.key == "pagedown":
            self.scroll_partial_page(direction=1)
            event.prevent_default()
            return

        # For other scroll keys (arrows, home, end), mark as user-scrolled
        # The default behavior will handle the actual scrolling
        elif event.key in ("up", "down", "home", "end"):
            self._user_scrolled = True
            self.auto_scroll = False

    def scroll_partial_page(self, direction: int) -> None:
        """Scroll a fraction of the viewport instead of a full page."""
        self._user_scrolled = True
        self.auto_scroll = False
        stride = max(self.size.height // 10, 3)  # 10% of viewport per page
        self.scroll_relative(y=direction * stride)

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        """Handle mouse scroll down (wheel down / two-finger swipe down)."""
        self._user_scrolled = True
        self.auto_scroll = False
        self.scroll_relative(y=3)  # Scroll 3 lines per tick
        event.stop()

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        """Handle mouse scroll up (wheel up / two-finger swipe up)."""
        self._user_scrolled = True
        self.auto_scroll = False
        self.scroll_relative(y=-3)  # Scroll 3 lines per tick
        self._reset_auto_scroll()  # Re-enable auto-scroll if at bottom
        event.stop()

    def on_mouse_down(self, event: MouseDown) -> None:
        """Track mouse down for drag detection."""
        self._mouse_down_pos = (event.x, event.y)

    def on_mouse_move(self, event: MouseMove) -> None:
        """Detect drag without Shift and show selection tip."""
        if self._mouse_down_pos and not event.shift:
            # User is dragging without Shift - show selection tip
            if hasattr(self.app, 'show_selection_tip'):
                self.app.show_selection_tip()
            self._mouse_down_pos = None  # Only show once per drag

    def on_mouse_up(self, event: MouseUp) -> None:
        """Clear mouse down tracking."""
        self._mouse_down_pos = None

    def _reset_auto_scroll(self) -> None:
        """Reset auto-scroll when new content arrives."""
        # When new content arrives, check if we should re-enable auto-scroll
        # If user hasn't manually scrolled away, enable auto-scroll
        if not self._user_scrolled:
            self.auto_scroll = True

        # If we're back at the bottom (within 2 lines), re-enable auto-scroll
        if self.scroll_offset.y >= self.max_scroll_y - 2:
            self._user_scrolled = False
            self.auto_scroll = True

    def add_user_message(self, message: str) -> None:
        # Add blank line before user prompt if previous line has content
        if self.lines and hasattr(self.lines[-1], 'plain'):
            last_plain = self.lines[-1].plain.strip() if self.lines[-1].plain else ""
            if last_plain:
                self.write(Text(""))
        self.write(Text(f"› {message}", style="bold white"))
        self.write(Text(""))

    def add_assistant_message(self, message: str) -> None:
        normalized = self._normalize_text(message)
        if normalized and normalized == self._last_assistant_rendered:
            return

        self._last_assistant_rendered = normalized
        segments = self._split_code_blocks(message)
        text_output = False
        leading_used = False

        for _, segment in enumerate(segments):
            if segment["type"] == "code":
                self._write_code_block(segment)
            else:
                content = segment["content"]
                if not content:
                    continue
                renderables, wrote = render_markdown_text_segment(
                    content,
                    leading=(not text_output and not leading_used),
                )
                for renderable in renderables:
                    self.write(renderable)
                if wrote:
                    text_output = True
                    leading_used = True

        self.write(Text(""))

    def add_system_message(self, message: str) -> None:
        self.write(Text(message, style="dim italic"))

    def add_error(self, message: str) -> None:
        """Render an error message with a red bullet and clear any active spinner."""
        self.stop_spinner()
        bullet = Text("⦿ ", style="bold red")
        bullet.append(message, style="red")
        self.write(bullet)
        self.write(Text(""))

    def add_tool_call(self, display: Text | str, *_: Any) -> None:
        # Add blank line before tool call if previous line has content
        if self._last_line_has_content:
            self.write(Text(""))

        if isinstance(display, Text):
            self._tool_display = display.copy()
        else:
            self._tool_display = Text(str(display), style="white")

        self._tool_call_start = len(self.lines)
        self._tool_timer_start = None
        self._tool_last_elapsed = None
        self._write_tool_call_line("⏺")

    def start_tool_execution(self) -> None:
        if self._tool_display is None:
            return

        self._spinner_active = True
        self._spinner_index = 0
        self._tool_timer_start = time.monotonic()
        self._tool_last_elapsed = None
        self._render_tool_spinner_frame()
        self._schedule_tool_spinner()

    def stop_tool_execution(self, success: bool = True) -> None:
        self._spinner_active = False
        if self._tool_timer_start is not None:
            self._tool_last_elapsed = max(int(time.monotonic() - self._tool_timer_start), 0)
        else:
            self._tool_last_elapsed = None
        self._tool_timer_start = None
        if self._tool_call_start is not None and self._tool_display is not None:
            self._replace_tool_call_line("⏺", success=success)

        self._tool_display = None
        self._tool_call_start = None
        self._spinner_index = 0
        if self._tool_spinner_timer is not None:
            self._tool_spinner_timer.stop()
            self._tool_spinner_timer = None

    def update_progress_text(self, message: str | Text) -> None:
        """Update the current progress/tool line text in-place.

        This updates the displayed text while keeping the spinner running
        and the timer accumulating. Use this for multi-step progress updates
        that should appear on the same line.

        Args:
            message: New text to display (replaces current text)
        """
        if self._tool_call_start is None:
            # No active progress line - start a new one
            self.add_tool_call(message)
            self.start_tool_execution()
            return

        # Update the display text
        if isinstance(message, Text):
            self._tool_display = message.copy()
        else:
            self._tool_display = Text(str(message), style="white")

        # Re-render the spinner frame with new text
        if self._spinner_active:
            self._render_tool_spinner_frame()

    def add_tool_result(self, result: str) -> None:
        try:
            result_plain = Text.from_markup(result).plain
        except Exception:
            result_plain = result

        header, diff_lines = self._extract_edit_payload(result_plain)
        if header:
            self._write_edit_result(header, diff_lines)
        else:
            self._write_generic_tool_result(result_plain)

        self.write(Text(""))

    def add_nested_tool_call(
        self,
        display: Text | str,
        depth: int,
        parent: str,
    ) -> None:
        """Add a nested tool call with indentation for subagent display.

        Args:
            display: The tool call display text
            depth: Nesting depth level (1 = direct child of main agent)
            parent: Name/identifier of the parent subagent
        """
        # Add blank line before nested tool call if previous line has content
        if self.lines and hasattr(self.lines[-1], 'plain'):
            last_plain = self.lines[-1].plain.strip() if self.lines[-1].plain else ""
            if last_plain:
                self.write(Text(""))

        if isinstance(display, Text):
            tool_text = display.copy()
        else:
            tool_text = Text(str(display), style="white")

        # Build indented line with bullet - START DIM to indicate "running"
        formatted = Text()
        indent = "  " * depth
        formatted.append(indent)
        formatted.append("⏺ ", style="dim green")  # Dim = running state
        formatted.append_text(tool_text)

        self.write(formatted, scroll_end=True, animate=False)

        # Track this nested tool call for pulsing animation
        self._nested_tool_line = len(self.lines) - 1
        self._nested_tool_text = tool_text.copy()
        self._nested_tool_depth = depth
        self._nested_pulse_bright = False  # Start dim (running)
        self._nested_pulse_counter = 0

    def complete_nested_tool_call(
        self,
        tool_name: str,
        depth: int,
        parent: str,
        success: bool,
    ) -> None:
        """Mark a nested tool call as complete.

        Args:
            tool_name: Name of the tool that completed
            depth: Nesting depth level
            parent: Name/identifier of the parent subagent
            success: Whether the tool execution succeeded
        """
        # Update the line to final state (green for success, red for failure)
        if self._nested_tool_line is not None and self._nested_tool_text is not None:
            self._nested_pulse_bright = True  # Bright = completed state
            self._pulse_nested_tool_line(success=success)

        # Clear nested tool tracking - this tool is no longer "running"
        self._nested_tool_line = None
        self._nested_tool_text = None

    def add_todo_sub_result(self, text: str, depth: int, is_last_parent: bool = True) -> None:
        """Add a single sub-result line for todo operations.

        Args:
            text: The sub-result text (e.g., "○ Create project structure")
            depth: Nesting depth for indentation
            is_last_parent: If True, no vertical continuation line (parent is last tool)
        """
        formatted = Text()
        indent = "  " * depth
        formatted.append(indent)
        # Use │ for vertical continuation only when more tools are coming
        prefix = "    └─ " if is_last_parent else "│   └─ "
        formatted.append(prefix, style="dim")
        formatted.append(text, style="dim")
        self.write(formatted, scroll_end=True, animate=False)

    def add_todo_sub_results(self, items: list, depth: int, is_last_parent: bool = True) -> None:
        """Add multiple sub-result lines for todo list operations.

        Args:
            items: List of (symbol, title) tuples
            depth: Nesting depth for indentation
            is_last_parent: If True, no vertical continuation line (parent is last tool)
        """
        indent = "  " * depth

        for i, (symbol, title) in enumerate(items):
            formatted = Text()
            formatted.append(indent)

            is_last_item = i == len(items) - 1
            # Use │ for vertical continuation only when more tools are coming
            if is_last_parent:
                prefix = "    └─ " if is_last_item else "    ├─ "
            else:
                prefix = "│   └─ " if is_last_item else "│   ├─ "

            formatted.append(prefix, style="dim")
            formatted.append(f"{symbol} {title}", style="dim")
            self.write(formatted, scroll_end=True, animate=False)

    def add_nested_tool_sub_results(self, lines: List[str], depth: int, is_last_parent: bool = True) -> None:
        """Add tool result lines with proper nesting indentation.

        This is the unified method for displaying subagent tool results,
        using the same formatting as the main agent via StyleFormatter.

        Args:
            lines: List of result lines from StyleFormatter._format_*_result() methods
            depth: Nesting depth for indentation
            is_last_parent: If True, no vertical continuation line (parent is last tool)
        """
        indent = "  " * depth

        # Flatten any multi-line strings into individual lines
        all_lines = []
        for line in lines:
            if '\n' in line:
                all_lines.extend(line.split('\n'))
            else:
                all_lines.append(line)

        # Filter trailing empty lines
        while all_lines and not all_lines[-1].strip():
            all_lines.pop()

        # Filter out empty lines and track non-empty ones for proper tree formatting
        non_empty_lines = [(i, line) for i, line in enumerate(all_lines) if line.strip()]

        # Check if any line contains error or interrupted markers - if so, all lines should be styled accordingly
        has_error = any(TOOL_ERROR_SENTINEL in line for _, line in non_empty_lines)
        has_interrupted = any("::interrupted::" in line for _, line in non_empty_lines)

        for idx, (orig_i, line) in enumerate(non_empty_lines):
            formatted = Text()
            formatted.append(indent)

            is_last_item = idx == len(non_empty_lines) - 1
            # Use │ for vertical continuation only when more tools are coming
            if is_last_parent:
                prefix = "    └─ " if is_last_item else "    ├─ "
            else:
                prefix = "│   └─ " if is_last_item else "│   ├─ "
            formatted.append(prefix, style="dim")

            # Strip markers from content
            clean_line = line.replace(TOOL_ERROR_SENTINEL, "").replace("::interrupted::", "").strip()
            # Strip ANSI codes for nested display (they don't render well in tree format)
            clean_line = re.sub(r"\x1b\[[0-9;]*m", "", clean_line)

            # Apply consistent styling based on error state
            if has_interrupted:
                formatted.append(clean_line, style="bold red")
            elif has_error:
                formatted.append(clean_line, style="red")
            else:
                formatted.append(clean_line, style="dim")

            self.write(formatted, scroll_end=True, animate=False)

    def add_edit_diff_result(self, diff_text: str, depth: int, is_last_parent: bool = True) -> None:
        """Add diff lines for edit_file result in subagent output.

        Args:
            diff_text: The unified diff text
            depth: Nesting depth for indentation
            is_last_parent: If True, no vertical continuation line (parent is last tool)
        """
        from swecli.ui_textual.formatters_internal.utils import DiffParser

        diff_entries = DiffParser.parse_unified_diff(diff_text)
        if not diff_entries:
            return

        indent = "  " * depth

        for i, (entry_type, line_no, content) in enumerate(diff_entries):
            formatted = Text()
            formatted.append(indent)

            is_last_item = i == len(diff_entries) - 1
            # Use │ for vertical continuation only when more tools are coming
            if is_last_parent:
                prefix = "    └─ " if is_last_item else "    ├─ "
            else:
                prefix = "│   └─ " if is_last_item else "│   ├─ "
            formatted.append(prefix, style="dim")

            if entry_type == "hunk":
                formatted.append(content, style="dim")
            elif entry_type == "add":
                display_no = f"{line_no:>4} " if line_no is not None else "     "
                formatted.append(display_no, style="dim")
                formatted.append("+ ", style="green")
                formatted.append(content.replace("\t", "    "), style="green")
            elif entry_type == "del":
                display_no = f"{line_no:>4} " if line_no is not None else "     "
                formatted.append(display_no, style="dim")
                formatted.append("- ", style="red")
                formatted.append(content.replace("\t", "    "), style="red")
            else:
                display_no = f"{line_no:>4} " if line_no is not None else "     "
                formatted.append(display_no, style="dim")
                formatted.append("  ", style="dim")
                formatted.append(content.replace("\t", "    "), style="dim")

            self.write(formatted, scroll_end=True, animate=False)

    def render_approval_prompt(self, lines: list[Text]) -> None:
        if self._approval_start is None:
            self._approval_start = len(self.lines)

        self._truncate_from(self._approval_start)

        for line in lines:
            self.write(line, scroll_end=True, animate=False)

    def clear_approval_prompt(self) -> None:
        if self._approval_start is None:
            return

        self._truncate_from(self._approval_start)
        self._approval_start = None

    # --- Private helpers -------------------------------------------------

    def _write_code_block(self, segment: dict[str, str]) -> None:
        code = segment["content"].strip("\n")
        if not code:
            return
        language = segment.get("language") or "text"
        syntax = Syntax(
            code,
            language,
            theme="monokai",
            line_numbers=bool(code.count("\n") > 0),
        )
        title = f"Code ({language})" if language and language != "text" else "Code"
        panel = Panel(syntax, title=title, border_style="bright_blue")
        self.write(panel)

    def _write_generic_tool_result(self, text: str) -> None:
        lines = text.rstrip("\n").splitlines() or [text]
        grey = "#a0a4ad"
        for raw_line in lines:
            line = Text("  ⎿  ", style=grey)
            message = raw_line.rstrip("\n")
            is_error = False
            is_interrupted = False
            if message.startswith(TOOL_ERROR_SENTINEL):
                is_error = True
                message = message[len(TOOL_ERROR_SENTINEL):].lstrip()
            elif message.startswith("::interrupted::"):
                is_interrupted = True
                message = message[len("::interrupted::"):].lstrip()

            if is_interrupted:
                line.append(message, style="bold red")
            else:
                line.append(message, style="red" if is_error else grey)
            self.write(line)

    def add_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = ".",
        depth: int = 0,
    ) -> None:
        """Render bash command output in VS Code Terminal style box.

        Args:
            output: The full bash output string
            is_error: Whether this is an error output (uses red styling)
            command: The command that was executed
            working_dir: The working directory
            depth: Nesting depth for subagent display
        """
        lines = output.rstrip("\n").splitlines()
        config = TerminalBoxConfig(
            command=command,
            working_dir=working_dir,
            depth=depth,
            is_error=is_error,
            box_width=self._get_box_width(),
        )
        for text_line in self._box_renderer.render_complete_box(lines, config):
            self.write(text_line)

    # --- Streaming bash box methods -------------------------------------------

    def _get_box_width(self) -> int:
        """Get box width based on widget size for dynamic sizing."""
        # Get widget width, leave margin for "  ⎿ " prefix (4 chars)
        available = (self.size.width or 120) - 4
        # Clamp between reasonable min/max
        return max(60, min(available, 120))

    def start_streaming_bash_box(self, command: str = "", working_dir: str = ".") -> None:
        """Start a VS Code-style terminal box with TERMINAL label and prompt line."""
        config = TerminalBoxConfig(
            command=command,
            working_dir=working_dir,
            depth=0,
            is_error=False,  # Unknown during streaming, always use default border
            box_width=self._get_box_width(),
        )
        
        # Store config for use in append and close
        self._streaming_box_config = config
        self._streaming_box_top_line = len(self.lines)
        
        # Render top border
        self.write(self._box_renderer.render_top_border(config))
        
        # Render padding line
        self.write(self._box_renderer.render_padding_line(config))
        
        # Render prompt line
        self._streaming_box_header_line = len(self.lines)
        self.write(self._box_renderer.render_prompt_line(config))
        
        # Store data for rebuild on close
        self._streaming_box_command = command
        self._streaming_box_working_dir = working_dir
        self._streaming_box_content_lines = []

    def append_to_streaming_box(self, line: str, is_stderr: bool = False) -> None:
        """Append a content line to the streaming box."""
        config = getattr(self, '_streaming_box_config', None)
        if config is None:
            # Fallback if config not set (shouldn't happen in normal flow)
            config = TerminalBoxConfig(box_width=self._get_box_width())
        
        # Render content line (no error styling during streaming)
        self.write(self._box_renderer.render_content_line(line, config, apply_error_style=False))
        
        # Store for rebuild on close
        self._streaming_box_content_lines.append((line, is_stderr))

    def close_streaming_bash_box(self, is_error: bool, exit_code: int) -> None:
        """Close box with padding and bottom border."""
        config = getattr(self, '_streaming_box_config', None)
        if config is None:
            # Fallback if config not set
            config = TerminalBoxConfig(box_width=self._get_box_width())
        
        # Render bottom padding and border (always gray - no transition)
        self.write(self._box_renderer.render_padding_line(config))
        self.write(self._box_renderer.render_bottom_border(config))
        
        # Reset state
        self._streaming_box_header_line = None
        self._streaming_box_top_line = None
        self._streaming_box_config = None
        self._streaming_box_command = ""
        self._streaming_box_working_dir = "."
        self._streaming_box_content_lines = []

    def add_nested_bash_output_box(
        self,
        output: str,
        is_error: bool,
        exit_code: int,
        command: str = "",
        working_dir: str = ".",
        depth: int = 0,
    ) -> None:
        """Render nested bash command output in VS Code Terminal style.

        Uses same visual format as streaming box but renders complete output at once.

        Args:
            output: The full bash output string
            is_error: Whether this is an error output
            exit_code: The command exit code
            command: The command that was executed
            working_dir: The working directory
            depth: Nesting depth for indentation
        """
        # Delegate to add_bash_output_box - they're now identical
        self.add_bash_output_box(
            output=output,
            is_error=is_error,
            command=command,
            working_dir=working_dir,
            depth=depth,
        )

    def _write_edit_result(self, header: str, diff_lines: list[str]) -> None:
        if not diff_lines:
            return

        self.write(Text(header, style="bold #d0d0d0"))
        match = re.search(r"Edit(?:ed)?\s+[\"']?([^\s\"']+)", header)
        title = match.group(1) if match else "diff"

        rendered_lines: List[Text] = []
        for raw_line in diff_lines:
            display = raw_line.rstrip("\n")
            if not display.strip():
                rendered_lines.append(Text(""))
                continue

            stripped = display.lstrip()
            style = "#d0d0d0"
            if stripped.startswith("+"):
                style = "green"
            elif stripped.startswith("-"):
                style = "red"
            elif stripped.startswith(("@@", "diff ", "index ", "---", "+++")):
                style = "cyan"
            rendered_lines.append(Text(display, style=style))

        panel = Panel(
            Group(*rendered_lines),
            border_style="#5a5a5a",
            padding=(0, 2),
            title=title,
            title_align="left",
        )
        self.write(panel)

    def _strip_tool_prefix(self, value: str) -> str:
        return re.sub(r"^\s*[⎿⏺•]\s+", "", value)

    def _extract_edit_payload(self, text: str) -> Tuple[str | None, list[str]]:
        lines = text.splitlines()
        if not lines:
            return None, []

        header = None
        payload_start = 0

        for idx, line in enumerate(lines):
            cleaned = self._strip_tool_prefix(line).strip()
            if not cleaned:
                continue
            if cleaned.startswith("Edit(") or cleaned.startswith("Edited "):
                header = cleaned
                payload_start = idx + 1
            break

        if not header:
            return None, []

        diff_lines = [
            self._strip_tool_prefix(ln.rstrip("\n"))
            for ln in lines[payload_start:]
        ]
        return header, diff_lines

    # --- Spinner handling ------------------------------------------------

    def start_spinner(self, message: Text | str) -> None:
        """Append spinner output at the end of the log."""
        # Add blank line before spinner if previous line has content
        if self.lines and hasattr(self.lines[-1], 'plain'):
            last_plain = self.lines[-1].plain.strip() if self.lines[-1].plain else ""
            if last_plain:
                self.write(Text(""))
        self._spinner_start = len(self.lines)
        self._append_spinner(message)

    def update_spinner(self, message: Text | str) -> None:
        """Update spinner output without growing the log."""
        if self._spinner_start is None:
            self.start_spinner(message)
            return

        self._remove_spinner_lines(preserve_index=True)
        self._append_spinner(message)

    def stop_spinner(self) -> None:
        """Remove the spinner message entirely."""
        if self._spinner_start is None:
            return

        self._remove_spinner_lines(preserve_index=False)
        self._spinner_start = None
        self._spinner_line_count = 0

    def _append_spinner(self, message: Text | str) -> None:
        text = message if isinstance(message, Text) else Text(message, style="bright_cyan")
        self.write(text, scroll_end=True, animate=False)
        if self._spinner_start is not None:
            self._spinner_line_count = len(self.lines) - self._spinner_start

    def _remove_spinner_lines(self, *, preserve_index: bool) -> None:
        if self._spinner_start is None:
            return

        start = min(self._spinner_start, len(self.lines))
        if start < len(self.lines):
            # Only delete non-protected lines
            to_delete = [i for i in range(start, len(self.lines)) if i not in self._protected_lines]
            for i in sorted(to_delete, reverse=True):
                if i < len(self.lines):
                    del self.lines[i]

            # Update protected line indices
            new_protected = set()
            for p in self._protected_lines:
                if p < start:
                    new_protected.add(p)
                else:
                    # Count deleted lines before this protected line
                    deleted_before = len([i for i in to_delete if i < p])
                    new_protected.add(p - deleted_before)
            self._protected_lines = new_protected

            self._line_cache.clear()
            widths: List[int] = []
            for strip in self.lines:
                cell_length = getattr(strip, "cell_length", None)
                widths.append(cell_length() if callable(cell_length) else cell_length or 0)
            self._widest_line_width = max(widths, default=0)
            self.virtual_size = Size(self._widest_line_width, len(self.lines))
            if self.auto_scroll:
                self.scroll_end(animate=False)
        else:
            self._spinner_start = len(self.lines)

        # Update _last_line_has_content to reflect actual last line state
        # This prevents add_tool_call() from seeing stale state
        if self.lines:
            last_line = self.lines[-1]
            # Check Strip objects (RichLog stores lines as Strip)
            if hasattr(last_line, '_segments'):
                segments = last_line._segments
                if len(segments) == 0:
                    self._last_line_has_content = False
                elif len(segments) == 1 and not segments[0].text.strip():
                    self._last_line_has_content = False
                else:
                    # Has content if any segment has non-empty text
                    self._last_line_has_content = any(s.text.strip() for s in segments)
            elif hasattr(last_line, 'plain'):
                self._last_line_has_content = bool(last_line.plain.strip())
            else:
                self._last_line_has_content = False
        else:
            self._last_line_has_content = False

        if preserve_index:
            self._spinner_line_count = 0
        else:
            self._spinner_start = None
            self._spinner_line_count = 0


    # --- Spinner handling ------------------------------------------------

    def _render_tool_spinner_frame(self) -> None:
        if self._tool_call_start is None or self._tool_display is None:
            return

        spinner_char = self._spinner_chars[self._spinner_index]
        self._replace_tool_call_line(spinner_char)

    def _replace_tool_call_line(self, prefix: str, success: bool = True) -> None:
        """Replace the tool call line in-place, preserving its position."""
        if self._tool_call_start is None or self._tool_display is None:
            return

        if self._tool_call_start >= len(self.lines):
            # Line index out of bounds, fall back to append
            self._tool_call_start = len(self.lines)
            self._write_tool_call_line(prefix)
            self._tool_call_start = len(self.lines) - 1
            return

        # Build the new line content
        formatted = Text()
        if prefix == "⏺":
            style = "green" if success else "red"
        else:
            style = "bright_cyan"
        formatted.append(f"{prefix} ", style=style)
        if self._tool_display is not None:
            formatted += self._tool_display.copy()
        timer = self._format_tool_timer()
        if timer is not None:
            formatted.append_text(timer)

        # Convert Text to Strip for in-place storage in RichLog
        from rich.console import Console
        from textual.strip import Strip

        # Use very large width and no_wrap to prevent text wrapping that causes corruption
        # The actual display will handle truncation at render time
        console = Console(width=1000, force_terminal=True, no_color=False)
        # Render with explicit options to avoid wrapping
        with console.capture() as capture:
            console.print(formatted, end="", overflow="ignore", no_wrap=True)
        # Get segments directly from the Text object instead of console render
        segments = list(formatted.render(console))
        strip = Strip(segments)

        # Update the line at the original position (in-place)
        self.lines[self._tool_call_start] = strip

        # Clear line cache for this line
        self._line_cache.clear()

        # Use RichLog's built-in refresh_line to update just this line
        self.refresh_line(self._tool_call_start)

        # Force screen compositor to update immediately
        if hasattr(self, 'app') and self.app is not None:
            self.app.refresh()

    def _write_tool_call_line(self, prefix: str) -> None:
        formatted = Text()
        style = "green" if prefix == "⏺" else "bright_cyan"
        formatted.append(f"{prefix} ", style=style)
        timer = self._format_tool_timer()
        if self._tool_display is not None:
            formatted += self._tool_display.copy()
        if timer is not None:
            formatted.append_text(timer)
        self.write(formatted, scroll_end=False, animate=False)

    def _tool_elapsed_seconds(self) -> int | None:
        if self._spinner_active and self._tool_timer_start is not None:
            return max(int(time.monotonic() - self._tool_timer_start), 0)
        if self._tool_last_elapsed is not None:
            return self._tool_last_elapsed
        return None

    def _format_tool_timer(self) -> Text | None:
        elapsed = self._tool_elapsed_seconds()
        if elapsed is None:
            return None
        return Text(f" ({elapsed}s)", style="#7a8594")

    def _schedule_tool_spinner(self) -> None:
        if not self._spinner_active:
            return
        if self._tool_spinner_timer is not None:
            self._tool_spinner_timer.stop()
        self._tool_spinner_timer = self.set_timer(0.12, self._animate_tool_spinner)

    def _animate_tool_spinner(self) -> None:
        if not self._spinner_active or self._tool_display is None or self._tool_call_start is None:
            return

        self._render_tool_spinner_frame()
        self._spinner_index = (self._spinner_index + 1) % len(self._spinner_chars)

        # Pulse nested tool indicator at slower rate (every 4 frames = ~0.5s)
        self._nested_pulse_counter += 1
        if self._nested_pulse_counter >= 4:
            self._nested_pulse_counter = 0
            self._nested_pulse_bright = not self._nested_pulse_bright
            self._pulse_nested_tool_line()

        self._schedule_tool_spinner()

    def _pulse_nested_tool_line(self, success: bool = True) -> None:
        """Update the nested tool call line with pulsing dim/bright effect."""
        if self._nested_tool_line is None or self._nested_tool_text is None:
            return

        if self._nested_tool_line >= len(self.lines):
            # Line index out of bounds
            return

        # Build the pulsed line
        formatted = Text()
        indent = "  " * self._nested_tool_depth
        formatted.append(indent)

        # Apply dim/bright pulsing to the bullet (red for failure, green for success)
        if success:
            bullet_style = "green" if self._nested_pulse_bright else "dim green"
        else:
            bullet_style = "red" if self._nested_pulse_bright else "dim red"
        formatted.append("⏺ ", style=bullet_style)
        formatted.append_text(self._nested_tool_text.copy())

        # Convert Text to Strip for in-place storage in RichLog
        from rich.console import Console
        from textual.strip import Strip

        # Use Text.render() instead of Console.render() for clean segments
        # Console.render() may add wrapping/transformations that cause corruption
        console = Console(width=1000, force_terminal=True, no_color=False)
        segments = list(formatted.render(console))
        strip = Strip(segments)

        # Update the line at the tracked position (in-place)
        self.lines[self._nested_tool_line] = strip

        # Clear cache and refresh display
        self._line_cache.clear()
        self.refresh()

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

    # --- Markdown helpers ------------------------------------------------

    def _split_code_blocks(self, message: str) -> list[dict[str, str]]:
        pattern = re.compile(r"```(\w+)?\n?(.*?)```", re.DOTALL)
        segments: list[dict[str, str]] = []
        last_end = 0

        for match in pattern.finditer(message):
            start, end = match.span()
            if start > last_end:
                segments.append({"type": "text", "content": message[last_end:start]})

            language = match.group(1) or ""
            code = match.group(2) or ""
            segments.append({"type": "code", "language": language, "content": code})
            last_end = end

        if last_end < len(message):
            segments.append({"type": "text", "content": message[last_end:]})

        if not segments:
            segments.append({"type": "text", "content": message})

        return segments

    @staticmethod
    def _normalize_text(message: str) -> str:
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", message)
        cleaned = cleaned.replace("⏺", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()
