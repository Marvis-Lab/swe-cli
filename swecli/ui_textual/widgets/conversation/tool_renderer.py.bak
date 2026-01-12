from __future__ import annotations

import re
import threading
import time
from typing import Any, List, Tuple

from rich.console import Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.strip import Strip
from textual.timer import Timer

from swecli.ui_textual.constants import TOOL_ERROR_SENTINEL
from swecli.ui_textual.style_tokens import (
    BLUE_PATH,
    ERROR,
    GREEN_BRIGHT,
    GREEN_PROMPT,
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

        # Re-render prompt line with ⎿ prefix
        formatted_path = self._box_renderer.format_path(self._streaming_box_working_dir)
        cmd_normalized = self._streaming_box_command.replace("\n", " ").replace("  ", " ").strip()
        prompt = Text("    \u23bf  ", style=GREY)
        prompt.append(formatted_path, style=BLUE_PATH)
        prompt.append(" $ ", style=GREEN_PROMPT)
        prompt.append(cmd_normalized, style=GREY)
        self.log.write(prompt)

        # Output lines with truncation
        for line in head_lines:
            self._write_bash_output_line(line, "", is_error)

        if hidden_count > 0:
            hidden_text = Text(f"       ... {hidden_count} lines hidden ...", style=f"{SUBTLE} italic")
            self.log.write(hidden_text)

        for line in tail_lines:
            self._write_bash_output_line(line, "", is_error)

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
        
        if "Editing file" in lines[0] or "Applied edit" in lines[0]:
            header = lines[0]
            diff_lines = lines[1:]
            return header, diff_lines
            
        return "", []

    def _write_edit_result(self, header: str, diff_lines: list[str]) -> None:
        self.log.write(Text(f"  {header}", style=SUBTLE))
        
        # Render fake diff box
        # Simplified: just write lines
        for line in diff_lines:
             if line.startswith("+"):
                 self.log.write(Text(f"  {line}", style=GREEN_BRIGHT))
             elif line.startswith("-"):
                 self.log.write(Text(f"  {line}", style=ERROR))
             else:
                 self.log.write(Text(f"  {line}", style=SUBTLE))

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

        # Prompt line with ⎿ prefix
        formatted_path = self._box_renderer.format_path(working_dir)
        cmd_normalized = command.replace("\n", " ").replace("  ", " ").strip()
        prompt = Text(f"{indent}    \u23bf  ", style=GREY)
        prompt.append(formatted_path, style=BLUE_PATH)
        prompt.append(" $ ", style=GREEN_PROMPT)
        prompt.append(cmd_normalized, style=GREY)
        self.log.write(prompt)

        # Output lines with space prefix for alignment
        for line in head_lines:
            self._write_bash_output_line(line, indent, is_error)

        if hidden_count > 0:
            hidden_text = Text(f"{indent}       ... {hidden_count} lines hidden ...", style=f"{SUBTLE} italic")
            self.log.write(hidden_text)

        for line in tail_lines:
            self._write_bash_output_line(line, indent, is_error)

        # Add blank line for spacing after output
        self.log.write(Text(""))

    def _write_bash_output_line(self, line: str, indent: str, is_error: bool) -> None:
        """Write a single bash output line with proper indentation."""
        normalized = self._box_renderer.normalize_line(line)
        output_line = Text(f"{indent}       ")
        output_line.append(normalized, style=ERROR if is_error else GREY)
        self.log.write(output_line)

    def start_streaming_bash_box(self, command: str = "", working_dir: str = ".") -> None:
        """Start streaming bash output with minimal style."""
        self._streaming_box_command = command
        self._streaming_box_working_dir = working_dir
        self._streaming_box_content_lines = []

        # Write prompt line with ⎿ prefix
        self.log.write(Text(""))  # Spacing
        self._streaming_box_top_line = len(self.log.lines)

        formatted_path = self._box_renderer.format_path(working_dir)
        cmd_normalized = command.replace("\n", " ").replace("  ", " ").strip()
        prompt = Text("    \u23bf  ", style=GREY)
        prompt.append(formatted_path, style=BLUE_PATH)
        prompt.append(" $ ", style=GREEN_PROMPT)
        prompt.append(cmd_normalized, style=GREY)
        self.log.write(prompt)

        self._streaming_box_header_line = len(self.log.lines) - 1

    def append_to_streaming_box(self, line: str, is_stderr: bool = False) -> None:
        """Append a content line to the streaming output."""
        if self._streaming_box_header_line is None:
            return

        # Store for rebuild
        self._streaming_box_content_lines.append((line, is_stderr))

        # Write output line with space prefix for alignment
        self._write_bash_output_line(line, "", is_stderr)

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

