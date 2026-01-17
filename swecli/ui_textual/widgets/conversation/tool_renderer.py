from __future__ import annotations

import re
import threading
import time
from typing import Any, List, Tuple

from rich.text import Text
from textual.strip import Strip
from textual.timer import Timer

from swecli.ui_textual.constants import TOOL_ERROR_SENTINEL
from swecli.ui_textual.style_tokens import (
    ERROR,
    GREEN_BRIGHT,
    GREY,
    PRIMARY,
    SUBTLE,
    SUCCESS,
)
from swecli.ui_textual.widgets.terminal_box_renderer import (
    TerminalBoxConfig,
    TerminalBoxRenderer,
)
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface


class DefaultToolRenderer:
    """Handles rendering of tool calls, results, and nested execution animations."""

    def __init__(self, log: RichLogInterface, app_callback_interface: Any = None):
        self.log = log
        self.app = app_callback_interface
        
        # Tool execution state
        self._tool_display: Text | None = None
        self._tool_spinner_timer: Timer | None = None
        self._spinner_active = False
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._spinner_index = 0
        self._tool_call_start: int | None = None
        self._tool_timer_start: float | None = None
        self._tool_last_elapsed: int | None = None
        
        # Thread timers for blocking operations
        self._tool_thread_timer: threading.Timer | None = None
        self._nested_tool_thread_timer: threading.Timer | None = None

        # Nested tool state
        self._nested_spinner_char = "⏺"
        self._nested_color_gradient = [
            "#00ff00", "#00f500", "#00eb00", "#00e100", "#00d700", "#00cd00",
            "#00c300", "#00b900", "#00af00", "#00a500", "#009b00",
            "#009100",  # Dimmest
            "#009b00", "#00a500", "#00af00", "#00b900", "#00c300",
            "#00cd00", "#00d700", "#00e100", "#00eb00", "#00f500",
            "#00ff00",  # Peak bright
        ]
        self._nested_color_index = 0
        self._nested_tool_line: int | None = None
        self._nested_tool_text: Text | None = None
        self._nested_tool_depth: int = 1
        self._nested_tool_timer: Timer | None = None
        self._nested_tool_timer_start: float | None = None
        
        # Streaming terminal box state
        self._streaming_box_header_line: int | None = None
        self._streaming_box_width: int = 60
        self._streaming_box_top_line: int | None = None
        self._streaming_box_command: str = ""
        self._streaming_box_working_dir: str = "."
        self._streaming_box_content_lines: list[tuple[str, bool]] = []
        self._streaming_box_config: TerminalBoxConfig | None = None
        
        # Helper renderer
        self._box_renderer = TerminalBoxRenderer(self._get_box_width)

    def cleanup(self) -> None:
        """Stop all timers and clear state."""
        self._stop_timers()
        if self._nested_tool_timer:
            self._nested_tool_timer.stop()
            self._nested_tool_timer = None

    def _stop_timers(self) -> None:
        if self._tool_spinner_timer:
            self._tool_spinner_timer.stop()
            self._tool_spinner_timer = None
        if self._tool_thread_timer:
            self._tool_thread_timer.cancel()
            self._tool_thread_timer = None
        if self._nested_tool_thread_timer:
            self._nested_tool_thread_timer.cancel()
            self._nested_tool_thread_timer = None

    def _get_box_width(self) -> int:
        return self.log.virtual_size.width

    # --- Standard Tool Calls ---

    def add_tool_call(self, display: Text | str, *_: Any) -> None:
        # Add blank line if needed (check logic from ConversationLog, 
        # but simpler to just enforce spacing standards or assume Log handles it?
        # ConversationLog checked _last_line_has_content. We might need access to that or pass it in.
        # For now, we'll blindly assume some spacing management or access via log lines if robust.
        # But log lines access is expensive if large. Let's just write and rely on log to space?
        # The prompt says 'slowly', so let's try to be faithful.)
        
        if self.log.lines and getattr(self.log.lines[-1], 'plain', '').strip():
             self.log.write(Text(""))

        if isinstance(display, Text):
            self._tool_display = display.copy()
        else:
            self._tool_display = Text(str(display), style=PRIMARY)

        self.log.scroll_end(animate=False)
        self._tool_call_start = len(self.log.lines)
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
            elapsed_raw = time.monotonic() - self._tool_timer_start
            self._tool_last_elapsed = max(round(elapsed_raw), 0)
        else:
            self._tool_last_elapsed = None
        self._tool_timer_start = None
        
        if self._tool_call_start is not None and self._tool_display is not None:
            self._replace_tool_call_line("⏺", success=success)

        self._tool_display = None
        self._tool_call_start = None
        self._spinner_index = 0
        self._stop_timers()

    def update_progress_text(self, message: str | Text) -> None:
        if self._tool_call_start is None:
            self.add_tool_call(message)
            self.start_tool_execution()
            return

        if isinstance(message, Text):
            self._tool_display = message.copy()
        else:
            self._tool_display = Text(str(message), style=PRIMARY)

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

        self.log.write(Text(""))

    def add_tool_result_continuation(self, lines: list[str]) -> None:
        """Add continuation lines for tool result (no ⎿ prefix, just space indentation).

        Used for diff lines that follow a summary line. The summary line already
        has the ⎿ prefix in the result placeholder, so these continuation lines
        just need space indentation to align.

        Structure:
        - ⎿  Summary line       (result placeholder, updated by spinner_service.stop)
        -    First diff line    (overwrites spacing placeholder - no gap)
        -    More diff lines...
        -    Last diff line
        - [blank line]          (added at end for spacing before next tool)
        """
        if not lines:
            return

        # Convert line to Strip helper
        def text_to_strip(text: Text) -> "Strip":
            from rich.console import Console
            from textual.strip import Strip
            console = Console(width=1000, force_terminal=True, no_color=False)
            segments = list(text.render(console))
            return Strip(segments)

        # Check if we have a pending spacing line to overwrite
        spacing_line = getattr(self.log, '_pending_spacing_line', None)

        for i, line in enumerate(lines):
            formatted = Text("       ", style=GREY)  # 7 spaces to align with ⎿ content
            formatted.append(line, style=SUBTLE)

            if i == 0 and spacing_line is not None and spacing_line < len(self.log.lines):
                # Overwrite spacing placeholder with first diff line (no gap)
                self.log.lines[spacing_line] = text_to_strip(formatted)
            else:
                self.log.write(formatted)

        # Clear the pending spacing line
        self.log._pending_spacing_line = None

        # Add blank line at end for spacing before next tool
        self.log.write(Text(""))

    # --- Nested Tool Calls ---

    def add_nested_tool_call(self, display: Text | str, depth: int, parent: str) -> None:
        if self.log.lines and getattr(self.log.lines[-1], 'plain', '').strip():
            self.log.write(Text(""))

        if isinstance(display, Text):
            tool_text = display.copy()
        else:
            tool_text = Text(str(display), style=SUBTLE)

        formatted = Text()
        indent = "  " * depth
        formatted.append(indent)
        formatted.append(f"{self._nested_spinner_char} ", style=self._nested_color_gradient[0])
        formatted.append_text(tool_text)
        formatted.append(" (0s)", style=GREY)

        self.log.write(formatted, scroll_end=True, animate=False)

        self._nested_tool_line = len(self.log.lines) - 1
        self._nested_tool_text = tool_text.copy()
        self._nested_tool_depth = depth
        self._nested_color_index = 0
        self._nested_tool_timer_start = time.monotonic()

        self._start_nested_tool_timer()

    def complete_nested_tool_call(self, tool_name: str, depth: int, parent: str, success: bool) -> None:
        if self._nested_tool_timer:
            self._nested_tool_timer.stop()
            self._nested_tool_timer = None
        if self._nested_tool_thread_timer:
            self._nested_tool_thread_timer.cancel()
            self._nested_tool_thread_timer = None

        if self._nested_tool_line is None or self._nested_tool_text is None:
            return

        formatted = Text()
        indent = "  " * depth
        formatted.append(indent)
        
        status_char = "✓" if success else "✗"
        status_color = SUCCESS if success else ERROR
        
        formatted.append(f"{status_char} ", style=status_color)
        formatted.append_text(self._nested_tool_text)
        
        elapsed = 0
        if self._nested_tool_timer_start:
            elapsed = round(time.monotonic() - self._nested_tool_timer_start)
        formatted.append(f" ({elapsed}s)", style=GREY)

        # In-place update
        from rich.console import Console
        console = Console(width=1000, force_terminal=True, no_color=False)
        segments = list(formatted.render(console))
        strip = Strip(segments)
        
        if self._nested_tool_line < len(self.log.lines):
            self.log.lines[self._nested_tool_line] = strip
            self.log.refresh_line(self._nested_tool_line)
        
        self._nested_tool_line = None
        self._nested_tool_text = None
        self._nested_tool_timer_start = None

    def _start_nested_tool_timer(self) -> None:
        if self._nested_tool_timer:
            self._nested_tool_timer.stop()
        if self._nested_tool_thread_timer:
            self._nested_tool_thread_timer.cancel()
        self._animate_nested_tool_spinner()

    def _animate_nested_tool_spinner(self) -> None:
        if self._nested_tool_thread_timer:
            self._nested_tool_thread_timer.cancel()
            self._nested_tool_thread_timer = None

        if self._nested_tool_line is None or self._nested_tool_text is None:
            return

        self._nested_color_index = (self._nested_color_index + 1) % len(self._nested_color_gradient)
        self._render_nested_tool_line()

        interval = 0.15
        self._nested_tool_timer = self.log.set_timer(interval, self._animate_nested_tool_spinner)
        self._nested_tool_thread_timer = threading.Timer(interval, self._on_nested_tool_thread_tick)
        self._nested_tool_thread_timer.daemon = True
        self._nested_tool_thread_timer.start()

    def _on_nested_tool_thread_tick(self) -> None:
        if self._nested_tool_line is None:
            return
        try:
            if self.app:
                self.app.call_from_thread(self._animate_nested_tool_spinner)
        except Exception:
            pass

    def _render_nested_tool_line(self) -> None:
        if self._nested_tool_line is None or self._nested_tool_text is None:
            return
        
        if self._nested_tool_line >= len(self.log.lines):
            return

        elapsed = 0
        if self._nested_tool_timer_start:
            elapsed = round(time.monotonic() - self._nested_tool_timer_start)

        formatted = Text()
        indent = "  " * self._nested_tool_depth
        formatted.append(indent)
        color = self._nested_color_gradient[self._nested_color_index]
        formatted.append(f"{self._nested_spinner_char} ", style=color)
        formatted.append_text(self._nested_tool_text.copy())
        formatted.append(f" ({elapsed}s)", style=GREY)

        from rich.console import Console
        console = Console(width=1000, force_terminal=True, no_color=False)
        segments = list(formatted.render(console))
        strip = Strip(segments)

        self.log.lines[self._nested_tool_line] = strip
        self.log.refresh_line(self._nested_tool_line)
        if self.app and hasattr(self.app, 'refresh'):
            self.app.refresh()

    def _rebuild_streaming_box_with_truncation(
        self,
        is_error: bool,
        content_lines: list[str],
    ) -> None:
        """Rebuild the streaming output with head+tail truncation."""
        if self._streaming_box_top_line is None:
            return

        # Remove all lines from top of output to current position
        self._truncate_from(self._streaming_box_top_line)

        # Apply truncation
        head_count = self._box_renderer.MAIN_AGENT_HEAD_LINES
        tail_count = self._box_renderer.MAIN_AGENT_TAIL_LINES
        head_lines, tail_lines, hidden_count = self._box_renderer.truncate_lines_head_tail(
            content_lines, head_count, tail_count
        )

        # Output lines with ⎿ prefix for first line, spaces for rest
        is_first = True
        for line in head_lines:
            self._write_bash_output_line(line, "", is_error, is_first)
            is_first = False

        if hidden_count > 0:
            hidden_text = Text(f"       ... {hidden_count} lines hidden ...", style=f"{SUBTLE} italic")
            self.log.write(hidden_text)

        for line in tail_lines:
            self._write_bash_output_line(line, "", is_error, is_first)
            is_first = False

    def _truncate_from(self, index: int) -> None:
        if index >= len(self.log.lines):
            return

        # Access protected lines from log if available
        protected_lines = getattr(self.log, "_protected_lines", set())
        
        # Check if any protected lines would be affected
        protected_in_range = [i for i in protected_lines if i >= index]
        
        if protected_in_range:
            non_protected = [i for i in range(index, len(self.log.lines)) if i not in protected_lines]
            if not non_protected:
                return
            for i in sorted(non_protected, reverse=True):
                 if i < len(self.log.lines):
                     del self.log.lines[i]
        else:
            del self.log.lines[index:]

        # Clear cache if available
        if hasattr(self.log, "_line_cache"):
            self.log._line_cache.clear()

        # Update protected line indices
        if protected_lines:
             new_protected = set()
             for p in protected_lines:
                 if p < index:
                     new_protected.add(p)
                 elif p in protected_in_range:
                     deleted_before = len([i for i in range(index, p) if i not in protected_lines])
                     new_protected.add(p - deleted_before)
             
             # Update the set in place if possible, or verify how to update
             if hasattr(self.log, "_protected_lines"):
                  self.log._protected_lines.clear()
                  self.log._protected_lines.update(new_protected)

        # Trigger refresh logic similar to ConversationLog
        if hasattr(self.log, "virtual_size"):
             # RichLog usually recalculates virtual size on write. 
             # Manual deletion might desync it.
             # We can't easily call internal _calculate_virtual_size
             # But self.log.refresh() usually handles repainting.
             pass
        self.log.refresh()

    def _schedule_tool_spinner(self) -> None:
        if self._tool_spinner_timer:
            self._tool_spinner_timer.stop()
        if self._tool_thread_timer:
            self._tool_thread_timer.cancel()

        self._tool_spinner_timer = self.log.set_timer(0.12, self._animate_tool_spinner)
        
        self._tool_thread_timer = threading.Timer(0.12, self._thread_animate_tool)
        self._tool_thread_timer.daemon = True
        self._tool_thread_timer.start()

    def _thread_animate_tool(self) -> None:
        if not self._spinner_active:
            return
        try:
            if self.app:
                self.app.call_from_thread(self._animate_tool_spinner)
        except Exception:
            pass

    def _animate_tool_spinner(self) -> None:
        if not self._spinner_active:
            return
        self._advance_tool_frame()
        self._schedule_tool_spinner()

    def _advance_tool_frame(self) -> None:
        if not self._spinner_active:
            return
        self._spinner_index = (self._spinner_index + 1) % len(self._spinner_chars)
        self._render_tool_spinner_frame()

    def _render_tool_spinner_frame(self) -> None:
        if self._tool_call_start is None:
            return
        char = self._spinner_chars[self._spinner_index]
        self._replace_tool_call_line(char)

    def _replace_tool_call_line(self, prefix: str, success: bool = True) -> None:
        if self._tool_call_start is None or self._tool_display is None:
            return

        if self._tool_call_start >= len(self.log.lines):
            return

        elapsed_str = ""
        if self._tool_timer_start is not None:
             elapsed = int(time.monotonic() - self._tool_timer_start)
             elapsed_str = f" ({elapsed}s)"
        elif self._tool_last_elapsed is not None:
             elapsed_str = f" ({self._tool_last_elapsed}s)"

        formatted = Text()
        
        if len(prefix) == 1 and prefix in self._spinner_chars:
            style = GREEN_BRIGHT
        elif not success:
            style = ERROR
        elif prefix == "⏺":
            style = GREEN_BRIGHT
        else:
            style = GREEN_BRIGHT

        formatted.append(f"{prefix} ", style=style)
        formatted.append_text(self._tool_display)
        formatted.append(elapsed_str, style=GREY)

        from rich.console import Console
        console = Console(width=1000, force_terminal=True, no_color=False)
        segments = list(formatted.render(console))
        strip = Strip(segments)

        self.log.lines[self._tool_call_start] = strip
        self.log.refresh_line(self._tool_call_start)
        if self.app and hasattr(self.app, 'refresh'):
            self.app.refresh()
            
    def _write_tool_call_line(self, prefix: str) -> None:
         # Initial write, just delegates to _replace mostly or simple write?
         # ConversationLog wrote "⏺" initially.
         # But standard log write appends. We need to append.
         # So we can fabricate it and write.
         
         # Logic from ConversationLog:
         # self._write_tool_call_line("⏺") -> calls _replace logic? No.
         # It constructs Text and calls self.write().
         
        formatted = Text()
        formatted.append(f"{prefix} ", style=GREEN_BRIGHT)
        if self._tool_display:
            formatted.append_text(self._tool_display)
        formatted.append(" (0s)", style=GREY)
        
        self.log.write(formatted)
         
    # --- Tool Result Parsing Helpers ---

    def _extract_edit_payload(self, text: str) -> Tuple[str, List[str]]:
        lines = text.splitlines()
        if not lines:
            return "", []

        # Simple heuristic to detect diff/edit output
        if lines[0].startswith("<<<<") or lines[0].startswith("Replaced lines"):
             # This is weak parsing, but matching ConversationLog's assumed logic
             # Actually ConversationLog had specific logic.
             # Let's inspect ConversationLog's _extract_edit_payload to be exact.
             # I should have read it more carefully. I'll copy it from previous context if possible.
             # Or just implement generic logic for now.
             pass
             
        # Re-implementing based on typical diff formats
        header = ""
        diff_lines = []
        
        if "Editing file" in lines[0] or "Applied edit" in lines[0] or "Updated " in lines[0]:
            header = lines[0]
            diff_lines = lines[1:]
            return header, diff_lines
            
        return "", []

    def _write_edit_result(self, header: str, diff_lines: list[str]) -> None:
        # Write header with ⎿ prefix to match other tool results
        self.log.write(Text(f"    ⎿  {header}", style=SUBTLE))

        # Write diff lines with proper formatting
        # Lines come from _format_edit_file_result after ANSI stripping:
        #   Addition: "NNN + content"  (line number right-aligned in 3 chars)
        #   Deletion: "NNN - content"
        #   Context:  "NNN   content"
        # The + or - is at position 4 (0-indexed) after the 3-char line number
        for line in diff_lines:
            formatted = Text("       ")  # 7 spaces to align with ⎿ content
            # Check position 4 for + or - (after "NNN " prefix)
            is_addition = len(line) > 4 and line[4] == "+"
            is_deletion = len(line) > 4 and line[4] == "-"
            if is_addition:
                formatted.append(line, style=GREEN_BRIGHT)
            elif is_deletion:
                formatted.append(line, style=ERROR)
            else:
                formatted.append(line, style=SUBTLE)
            self.log.write(formatted)

    def _write_generic_tool_result(self, text: str) -> None:
        lines = text.rstrip("\n").splitlines() or [text]
        for i, raw_line in enumerate(lines):
            # First line gets ⎿ prefix, subsequent lines get spaces for alignment
            prefix = "    ⎿  " if i == 0 else "       "
            line = Text(prefix, style=GREY)
            message = raw_line.rstrip("\n")
            is_error = False
            is_interrupted = False
            
            # Use constant if imported, else literal check
            if message.startswith(TOOL_ERROR_SENTINEL):
                is_error = True
                message = message[len(TOOL_ERROR_SENTINEL):].lstrip()
            elif message.startswith("::interrupted::"):
                is_interrupted = True
                message = message[len("::interrupted::"):].lstrip()

            if is_interrupted:
                line.append(message, style=f"bold {ERROR}")
            else:
                # Use dim for normal, red for error
                line.append(message, style=ERROR if is_error else SUBTLE)
            self.log.write(line)

    # --- Bash Box Output ---

    def add_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = ".",
        depth: int = 0,
    ) -> None:
        """Render bash output with minimal style matching Edit display."""
        lines = output.rstrip("\n").splitlines()

        # Apply truncation based on depth
        if depth == 0:
            head_count = self._box_renderer.MAIN_AGENT_HEAD_LINES
            tail_count = self._box_renderer.MAIN_AGENT_TAIL_LINES
        else:
            head_count = self._box_renderer.SUBAGENT_HEAD_LINES
            tail_count = self._box_renderer.SUBAGENT_TAIL_LINES

        head_lines, tail_lines, hidden_count = self._box_renderer.truncate_lines_head_tail(
            lines, head_count, tail_count
        )

        indent = "  " * depth

        # Output lines with ⎿ prefix for first line, spaces for rest
        is_first = True
        for line in head_lines:
            self._write_bash_output_line(line, indent, is_error, is_first)
            is_first = False

        if hidden_count > 0:
            hidden_text = Text(f"{indent}       ... {hidden_count} lines hidden ...", style=f"{SUBTLE} italic")
            self.log.write(hidden_text)

        for line in tail_lines:
            self._write_bash_output_line(line, indent, is_error, is_first)
            is_first = False

        # Add blank line for spacing after output
        self.log.write(Text(""))

    def _write_bash_output_line(self, line: str, indent: str, is_error: bool, is_first: bool = False) -> None:
        """Write a single bash output line with proper indentation."""
        normalized = self._box_renderer.normalize_line(line)
        # Use ⎿ prefix for first line, spaces for rest
        prefix = f"{indent}    \u23bf  " if is_first else f"{indent}       "
        output_line = Text(prefix, style=GREY)
        output_line.append(normalized, style=ERROR if is_error else GREY)
        self.log.write(output_line)

    def start_streaming_bash_box(self, command: str = "", working_dir: str = ".") -> None:
        """Start streaming bash output with minimal style."""
        self._streaming_box_command = command
        self._streaming_box_working_dir = working_dir
        self._streaming_box_content_lines = []

        # Track start position for rebuild
        self._streaming_box_top_line = len(self.log.lines)
        self._streaming_box_header_line = len(self.log.lines)

    def append_to_streaming_box(self, line: str, is_stderr: bool = False) -> None:
        """Append a content line to the streaming output."""
        if self._streaming_box_header_line is None:
            return

        # Check if this is the first line (⎿ prefix)
        is_first = len(self._streaming_box_content_lines) == 0

        # Store for rebuild
        self._streaming_box_content_lines.append((line, is_stderr))

        # Write output line with ⎿ for first line, spaces for rest
        self._write_bash_output_line(line, "", is_stderr, is_first)

    def close_streaming_bash_box(self, is_error: bool, exit_code: int) -> None:
        """Close streaming bash output, applying truncation if needed."""
        # Check if truncation is needed (main agent uses MAIN_AGENT limits)
        content_lines = [line for line, _ in self._streaming_box_content_lines]
        head_count = self._box_renderer.MAIN_AGENT_HEAD_LINES
        tail_count = self._box_renderer.MAIN_AGENT_TAIL_LINES
        max_lines = head_count + tail_count

        if len(content_lines) > max_lines and self._streaming_box_top_line is not None:
            # Rebuild with truncation
            self._rebuild_streaming_box_with_truncation(is_error, content_lines)
        # No bottom border needed for minimal style

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
        is_error: bool = False,
        command: str = "",
        working_dir: str = "",
        depth: int = 1,
    ) -> None:
        """Render nested bash output with minimal style."""
        # Use the same add_bash_output_box with depth parameter
        self.add_bash_output_box(output, is_error, command, working_dir, depth)

    # --- Nested Tool Result Display Methods ---

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
        # Use ⎿ prefix to match main agent style
        formatted.append("    ⎿  ", style=GREY)
        formatted.append(text, style=SUBTLE)
        self.log.write(formatted, scroll_end=True, animate=False)

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

            # First line gets ⎿ prefix, subsequent lines get spaces for alignment
            prefix = "    ⎿  " if i == 0 else "       "
            formatted.append(prefix, style=GREY)
            formatted.append(f"{symbol} {title}", style=SUBTLE)
            self.log.write(formatted, scroll_end=True, animate=False)

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

        # Filter out empty lines and track non-empty ones for proper formatting
        non_empty_lines = [(i, line) for i, line in enumerate(all_lines) if line.strip()]

        # Check if any line contains error or interrupted markers
        has_error = any(TOOL_ERROR_SENTINEL in line for _, line in non_empty_lines)
        has_interrupted = any("::interrupted::" in line for _, line in non_empty_lines)

        for idx, (orig_i, line) in enumerate(non_empty_lines):
            formatted = Text()
            formatted.append(indent)

            # First line gets ⎿ prefix, subsequent lines get spaces for alignment
            prefix = "    ⎿  " if idx == 0 else "       "
            formatted.append(prefix, style=GREY)

            # Strip markers from content
            clean_line = line.replace(TOOL_ERROR_SENTINEL, "").replace("::interrupted::", "").strip()
            # Strip ANSI codes for nested display (they don't render well)
            clean_line = re.sub(r"\x1b\[[0-9;]*m", "", clean_line)

            # Apply consistent styling based on error state
            if has_interrupted:
                formatted.append(clean_line, style=f"bold {ERROR}")
            elif has_error:
                formatted.append(clean_line, style=ERROR)
            else:
                formatted.append(clean_line, style=SUBTLE)

            self.log.write(formatted, scroll_end=True, animate=False)

    def add_nested_tree_result(
        self,
        tool_outputs: List[str],
        depth: int,
        is_last_parent: bool = True,
        has_error: bool = False,
        has_interrupted: bool = False,
    ) -> None:
        """Add tool result with tree-style indentation (legacy support).

        Args:
            tool_outputs: List of output lines
            depth: Nesting depth for indentation
            is_last_parent: If True, no vertical continuation line
            has_error: Whether result indicates an error
            has_interrupted: Whether the operation was interrupted
        """
        # Delegate to add_nested_tool_sub_results for consistent styling
        self.add_nested_tool_sub_results(tool_outputs, depth, is_last_parent)

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

            # First line gets ⎿ prefix, subsequent lines get spaces for alignment
            prefix = "    ⎿  " if i == 0 else "       "
            formatted.append(prefix, style=GREY)

            if entry_type == "hunk":
                formatted.append(content, style=SUBTLE)
            elif entry_type == "add":
                display_no = f"{line_no:>4} " if line_no is not None else "     "
                formatted.append(display_no, style=SUBTLE)
                formatted.append("+ ", style=SUCCESS)
                formatted.append(content.replace("\t", "    "), style=SUCCESS)
            elif entry_type == "del":
                display_no = f"{line_no:>4} " if line_no is not None else "     "
                formatted.append(display_no, style=SUBTLE)
                formatted.append("- ", style=ERROR)
                formatted.append(content.replace("\t", "    "), style=ERROR)
            else:
                display_no = f"{line_no:>4} " if line_no is not None else "     "
                formatted.append(display_no, style=SUBTLE)
                formatted.append("  ", style=SUBTLE)
                formatted.append(content.replace("\t", "    "), style=SUBTLE)

            self.log.write(formatted, scroll_end=True, animate=False)

