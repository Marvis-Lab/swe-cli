from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.strip import Strip
from textual.timer import Timer

from swecli.ui_textual.constants import TOOL_ERROR_SENTINEL
from swecli.ui_textual.style_tokens import (
    BLUE_PATH,
    CYAN,
    ERROR,
    GREEN_BRIGHT,
    GREEN_GRADIENT,
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
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager
from swecli.ui_textual.models.collapsible_output import CollapsibleOutput
from swecli.ui_textual.utils.output_summarizer import summarize_output, get_expansion_hint

# Re-exports for backward compatibility and internal use
from swecli.ui_textual.widgets.conversation.renderers.models import (
    AgentInfo,
    ParallelAgentGroup,
    SingleAgentInfo,
    NestedToolState,
    AgentStats,
)
from swecli.ui_textual.widgets.conversation.renderers.parallel_agent_renderer import ParallelAgentRenderer
from swecli.ui_textual.widgets.conversation.renderers.single_agent_renderer import SingleAgentRenderer
from swecli.ui_textual.widgets.conversation.renderers.nested_tool_renderer import NestedToolRenderer
from swecli.ui_textual.widgets.conversation.renderers.utils import (
    TREE_BRANCH,
    TREE_LAST,
    TREE_VERTICAL,
    TREE_CONTINUATION,
    text_to_strip,
)


class DefaultToolRenderer:
    """Handles rendering of tool calls, results, and nested execution animations."""

    def __init__(self, log: RichLogInterface, app_callback_interface: Any = None):
        self.log = log
        self.app = app_callback_interface
        self._spacing = SpacingManager(log)

        # Sub-renderers
        self.parallel_renderer = ParallelAgentRenderer(log, self._spacing)
        self.single_renderer = SingleAgentRenderer(log, self._spacing)
        self.nested_renderer = NestedToolRenderer(log, self._spacing)

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

        # Nested tool timer
        self._nested_tool_timer: Timer | None = None

        # Local state for parallel expansion default
        self._parallel_expanded_default: bool = False

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

        # Collapsible output tracking: line_index -> CollapsibleOutput
        self._collapsible_outputs: Dict[int, CollapsibleOutput] = {}
        # Track most recent collapsible output for quick access
        self._most_recent_collapsible: Optional[int] = None

        # Resize coordination
        self._paused_for_resize = False

    @property
    def _parallel_group(self) -> Optional[ParallelAgentGroup]:
        return self.parallel_renderer.group

    @_parallel_group.setter
    def _parallel_group(self, value: Optional[ParallelAgentGroup]) -> None:
        self.parallel_renderer.group = value

    @property
    def _single_agent(self) -> Optional[SingleAgentInfo]:
        return self.single_renderer.agent

    @_single_agent.setter
    def _single_agent(self, value: Optional[SingleAgentInfo]) -> None:
        self.single_renderer.agent = value

    @property
    def _parallel_expanded(self) -> bool:
        if self.parallel_renderer.group:
            return self.parallel_renderer.group.expanded
        return self._parallel_expanded_default

    @_parallel_expanded.setter
    def _parallel_expanded(self, value: bool) -> None:
        self._parallel_expanded_default = value
        if self.parallel_renderer.group:
            self.parallel_renderer.group.expanded = value

    # Compatibility properties for nested renderer
    @property
    def _nested_tools(self) -> Dict[Tuple[str, str], NestedToolState]:
        return self.nested_renderer.tools

    @property
    def _nested_tool_line(self) -> Optional[int]:
        return self.nested_renderer.legacy_line

    @_nested_tool_line.setter
    def _nested_tool_line(self, value: Optional[int]) -> None:
        self.nested_renderer.legacy_line = value

    @property
    def _nested_tool_text(self) -> Optional[Text]:
        return self.nested_renderer.legacy_text

    @_nested_tool_text.setter
    def _nested_tool_text(self, value: Optional[Text]) -> None:
        self.nested_renderer.legacy_text = value

    def cleanup(self) -> None:
        """Stop all timers and clear state."""
        self._stop_timers()
        if self._nested_tool_timer:
            self._nested_tool_timer.stop()
            self._nested_tool_timer = None

    # --- Resize Coordination Methods ---

    def pause_for_resize(self) -> None:
        """Stop animation timers for resize."""
        self._paused_for_resize = True
        self._stop_timers()
        if self._nested_tool_timer:
            self._nested_tool_timer.stop()
            self._nested_tool_timer = None

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        """Adjust all tracked line indices by delta."""
        def adj(idx: Optional[int]) -> Optional[int]:
            return idx + delta if idx is not None and idx >= first_affected else idx

        # Adjust tool call tracking
        self._tool_call_start = adj(self._tool_call_start)

        # Delegate to sub-renderers
        self.nested_renderer.adjust_indices(delta, first_affected)
        self.parallel_renderer.adjust_indices(delta, first_affected)
        self.single_renderer.adjust_indices(delta, first_affected)

        # Adjust streaming box lines
        self._streaming_box_header_line = adj(self._streaming_box_header_line)
        self._streaming_box_top_line = adj(self._streaming_box_top_line)

        # Adjust collapsible outputs
        new_collapsibles: Dict[int, CollapsibleOutput] = {}
        for start, coll in self._collapsible_outputs.items():
            new_start = start + delta if start >= first_affected else start
            coll.start_line = new_start
            if coll.end_line >= first_affected:
                coll.end_line += delta
            new_collapsibles[new_start] = coll
        self._collapsible_outputs = new_collapsibles

        # Adjust most recent collapsible pointer
        self._most_recent_collapsible = adj(self._most_recent_collapsible)

    def resume_after_resize(self) -> None:
        """Restart animations after resize."""
        self._paused_for_resize = False

        has_active = (
            self.nested_renderer.has_active_tools()
            or self.parallel_renderer.has_active_group()
            or self.single_renderer.has_active_agent()
        )

        if has_active and self._nested_tool_timer is None:
            self._animate_nested_tool_spinner()

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
        self._spacing.before_tool_call()

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

        self._spacing.after_tool_result()

    def add_tool_result_continuation(self, lines: list[str]) -> None:
        if not lines:
            return

        spacing_line = getattr(self.log, "_pending_spacing_line", None)

        for i, line in enumerate(lines):
            formatted = Text("     ", style=GREY)
            formatted.append(line, style=SUBTLE)

            if i == 0 and spacing_line is not None and spacing_line < len(self.log.lines):
                self.log.lines[spacing_line] = text_to_strip(formatted)
            else:
                self.log.write(formatted, wrappable=False)

        self.log._pending_spacing_line = None
        self._spacing.after_tool_result_continuation()

    # --- Nested Tool Calls ---

    def add_nested_tool_call(
        self,
        display: Text | str,
        depth: int,
        parent: str,
        tool_id: str = "",
        is_last: bool = False,
    ) -> None:
        # Check single agent first
        if self.single_renderer.has_active_agent():
            tool_text = display if isinstance(display, Text) else Text(str(display), style=SUBTLE)
            plain_text = tool_text.plain if hasattr(tool_text, "plain") else str(tool_text)
            if ":" in plain_text:
                tool_name = plain_text.split(":")[0].strip()
            elif "(" in plain_text:
                tool_name = plain_text.split("(")[0].strip()
            else:
                tool_name = plain_text.split()[0] if plain_text.split() else "unknown"

            self.single_renderer.update_tool(plain_text)
            return

        # Check parallel group
        if self.parallel_renderer.has_active_group():
            tool_text = display if isinstance(display, Text) else Text(str(display), style=SUBTLE)
            plain_text = tool_text.plain if hasattr(tool_text, "plain") else str(tool_text)
            if ":" in plain_text:
                tool_name = plain_text.split(":")[0].strip()
            elif "(" in plain_text:
                tool_name = plain_text.split("(")[0].strip()
            else:
                tool_name = plain_text.split()[0] if plain_text.split() else "unknown"

            self.parallel_renderer.update_agent_tool(parent, plain_text)

            # If not expanded, we are done
            if not self._parallel_expanded:
                return

        # Delegate to nested renderer
        self.nested_renderer.add_tool(display, depth, parent, tool_id, is_last)
        self._start_nested_tool_timer()

    def complete_nested_tool_call(
        self,
        tool_name: str,
        depth: int,
        parent: str,
        success: bool,
        tool_id: str = "",
    ) -> None:
        self.nested_renderer.complete_tool(tool_name, depth, parent, success, tool_id)

        # Stop timers only if no more active tools/agents
        has_active = (
            self.nested_renderer.has_active_tools()
            or self.parallel_renderer.has_active_group()
            or self.single_renderer.has_active_agent()
        )
        if not has_active:
            if self._nested_tool_timer:
                self._nested_tool_timer.stop()
                self._nested_tool_timer = None
            if self._nested_tool_thread_timer:
                self._nested_tool_thread_timer.cancel()
                self._nested_tool_thread_timer = None

    def _start_nested_tool_timer(self) -> None:
        if self._nested_tool_timer is None:
            self._animate_nested_tool_spinner()

    def _animate_nested_tool_spinner(self) -> None:
        if self._paused_for_resize:
            return

        if self._nested_tool_thread_timer:
            self._nested_tool_thread_timer.cancel()
            self._nested_tool_thread_timer = None

        has_active = (
            self.nested_renderer.has_active_tools()
            or self.parallel_renderer.has_active_group()
            or self.single_renderer.has_active_agent()
        )

        if not has_active:
            self._nested_tool_timer = None
            return

        # Delegate animation to sub-renderers
        self.nested_renderer.animate()
        self.parallel_renderer.animate()
        self.single_renderer.animate()

        interval = 0.15
        self._nested_tool_timer = self.log.set_timer(interval, self._animate_nested_tool_spinner)
        self._nested_tool_thread_timer = threading.Timer(interval, self._on_nested_tool_thread_tick)
        self._nested_tool_thread_timer.daemon = True
        self._nested_tool_thread_timer.start()

    def _on_nested_tool_thread_tick(self) -> None:
        if not (
            self.nested_renderer.has_active_tools()
            or self.parallel_renderer.has_active_group()
            or self.single_renderer.has_active_agent()
        ):
            return
        try:
            if self.app:
                self.app.call_from_thread(self._animate_nested_tool_spinner)
        except Exception:
            pass

    # --- Parallel Agent Group Management ---

    def on_parallel_agents_start(self, agent_infos: List[dict]) -> None:
        self.parallel_renderer.start(agent_infos, self._parallel_expanded_default)
        self._start_nested_tool_timer()

    def on_parallel_agent_complete(self, tool_call_id: str, success: bool) -> None:
        self.parallel_renderer.complete_agent(tool_call_id, success)

    def on_parallel_agents_done(self) -> None:
        self.parallel_renderer.done()

    def toggle_parallel_expansion(self) -> bool:
        new_state = not self._parallel_expanded
        self._parallel_expanded = new_state
        return new_state

    def has_active_parallel_group(self) -> bool:
        return self.parallel_renderer.has_active_group()

    # --- Single Agent Management ---

    def on_single_agent_start(self, agent_type: str, description: str, tool_call_id: str) -> None:
        self.single_renderer.start(agent_type, description, tool_call_id)
        self._start_nested_tool_timer()

    def on_single_agent_complete(self, tool_call_id: str, success: bool = True) -> None:
        self.single_renderer.complete(tool_call_id, success)

    # --- Box Output and Helpers ---

    def _rebuild_streaming_box_with_truncation(
        self,
        is_error: bool,
        content_lines: list[str],
    ) -> None:
        if self._streaming_box_top_line is None:
            return

        self._truncate_from(self._streaming_box_top_line)

        head_count = self._box_renderer.MAIN_AGENT_HEAD_LINES
        tail_count = self._box_renderer.MAIN_AGENT_TAIL_LINES
        head_lines, tail_lines, hidden_count = self._box_renderer.truncate_lines_head_tail(
            content_lines, head_count, tail_count
        )

        is_first = True
        for line in head_lines:
            self._write_bash_output_line(line, "", is_error, is_first)
            is_first = False

        if hidden_count > 0:
            hidden_text = Text(
                f"       ... {hidden_count} lines hidden ...", style=f"{SUBTLE} italic"
            )
            self.log.write(hidden_text, wrappable=False)

        for line in tail_lines:
            self._write_bash_output_line(line, "", is_error, is_first)
            is_first = False

    def _truncate_from(self, index: int) -> None:
        if index >= len(self.log.lines):
            return

        protected_lines = getattr(self.log, "_protected_lines", set())
        protected_in_range = [i for i in protected_lines if i >= index]

        if protected_in_range:
            non_protected = [
                i for i in range(index, len(self.log.lines)) if i not in protected_lines
            ]
            if not non_protected:
                return
            for i in sorted(non_protected, reverse=True):
                if i < len(self.log.lines):
                    del self.log.lines[i]
        else:
            del self.log.lines[index:]

        if hasattr(self.log, "_line_cache"):
            self.log._line_cache.clear()

        if protected_lines:
            new_protected = set()
            for p in protected_lines:
                if p < index:
                    new_protected.add(p)
                elif p in protected_in_range:
                    deleted_before = len([i for i in range(index, p) if i not in protected_lines])
                    new_protected.add(p - deleted_before)

            if hasattr(self.log, "_protected_lines"):
                self.log._protected_lines.clear()
                self.log._protected_lines.update(new_protected)

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

        self.log.lines[self._tool_call_start] = text_to_strip(formatted)
        self.log.refresh_line(self._tool_call_start)
        if self.app and hasattr(self.app, "refresh"):
            self.app.refresh()

    def _write_tool_call_line(self, prefix: str) -> None:
        formatted = Text()
        formatted.append(f"{prefix} ", style=GREEN_BRIGHT)
        if self._tool_display:
            formatted.append_text(self._tool_display)
        formatted.append(" (0s)", style=GREY)
        self.log.write(formatted, wrappable=False)

    def _extract_edit_payload(self, text: str) -> Tuple[str, List[str]]:
        lines = text.splitlines()
        if not lines:
            return "", []

        if "Editing file" in lines[0] or "Applied edit" in lines[0] or "Updated " in lines[0]:
            header = lines[0]
            diff_lines = lines[1:]
            return header, diff_lines

        return "", []

    def _write_edit_result(self, header: str, diff_lines: list[str]) -> None:
        self.log.write(Text(f"  ⎿  {header}", style=SUBTLE), wrappable=True)

        for line in diff_lines:
            formatted = Text("     ")
            is_addition = len(line) > 4 and line[4] == "+"
            is_deletion = len(line) > 4 and line[4] == "-"
            if is_addition:
                formatted.append(line, style=GREEN_BRIGHT)
            elif is_deletion:
                formatted.append(line, style=ERROR)
            else:
                formatted.append(line, style=SUBTLE)
            self.log.write(formatted, wrappable=False)

    def _write_generic_tool_result(self, text: str) -> None:
        lines = text.rstrip("\n").splitlines() or [text]
        for i, raw_line in enumerate(lines):
            prefix = "  ⎿  " if i == 0 else "     "
            line = Text(prefix, style=GREY)
            message = raw_line.rstrip("\n")
            is_error = False
            is_interrupted = False

            if message.startswith(TOOL_ERROR_SENTINEL):
                is_error = True
                message = message[len(TOOL_ERROR_SENTINEL) :].lstrip()
            elif message.startswith("::interrupted::"):
                is_interrupted = True
                message = message[len("::interrupted::") :].lstrip()

            if is_interrupted:
                line.append(message, style=f"bold {ERROR}")
            else:
                line.append(message, style=ERROR if is_error else SUBTLE)
            self.log.write(line, wrappable=False)

    def add_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = ".",
        depth: int = 0,
    ) -> None:
        lines = output.rstrip("\n").splitlines()

        if depth == 0:
            head_count = self._box_renderer.MAIN_AGENT_HEAD_LINES
            tail_count = self._box_renderer.MAIN_AGENT_TAIL_LINES
        else:
            head_count = self._box_renderer.SUBAGENT_HEAD_LINES
            tail_count = self._box_renderer.SUBAGENT_TAIL_LINES

        max_lines = head_count + tail_count
        should_collapse = len(lines) > max_lines

        indent = "  " * depth

        if should_collapse:
            start_line = len(self.log.lines)

            summary = summarize_output(lines, "bash")
            hint = get_expansion_hint()
            summary_line = Text(f"{indent}  \u23bf  ", style=GREY)
            summary_line.append(summary, style=SUBTLE)
            summary_line.append(f" {hint}", style=f"{SUBTLE} italic")
            self.log.write(summary_line, wrappable=False)

            end_line = len(self.log.lines) - 1

            collapsible = CollapsibleOutput(
                start_line=start_line,
                end_line=end_line,
                full_content=lines,
                summary=summary,
                is_expanded=False,
                output_type="bash",
                command=command,
                working_dir=working_dir,
                is_error=is_error,
                depth=depth,
            )
            self._collapsible_outputs[start_line] = collapsible
            self._most_recent_collapsible = start_line
        else:
            is_first = True
            for line in lines:
                self._write_bash_output_line(line, indent, is_error, is_first)
                is_first = False

        self._spacing.after_bash_output_box()

    def _write_bash_output_line(
        self, line: str, indent: str, is_error: bool, is_first: bool = False
    ) -> None:
        normalized = self._box_renderer.normalize_line(line)
        prefix = f"{indent}  \u23bf  " if is_first else f"{indent}     "
        output_line = Text(prefix, style=GREY)
        output_line.append(normalized, style=ERROR if is_error else GREY)
        self.log.write(output_line, wrappable=False)

    def start_streaming_bash_box(self, command: str = "", working_dir: str = ".") -> None:
        self._streaming_box_command = command
        self._streaming_box_working_dir = working_dir
        self._streaming_box_content_lines = []
        self._streaming_box_top_line = len(self.log.lines)
        self._streaming_box_header_line = len(self.log.lines)

    def append_to_streaming_box(self, line: str, is_stderr: bool = False) -> None:
        if self._streaming_box_header_line is None:
            return

        is_first = len(self._streaming_box_content_lines) == 0
        self._streaming_box_content_lines.append((line, is_stderr))
        self._write_bash_output_line(line, "", is_stderr, is_first)

    def close_streaming_bash_box(self, is_error: bool, exit_code: int) -> None:
        content_lines = [line for line, _ in self._streaming_box_content_lines]
        head_count = self._box_renderer.MAIN_AGENT_HEAD_LINES
        tail_count = self._box_renderer.MAIN_AGENT_TAIL_LINES
        max_lines = head_count + tail_count

        if len(content_lines) > max_lines and self._streaming_box_top_line is not None:
            self._rebuild_streaming_box_as_collapsed(is_error, content_lines)

        self._streaming_box_header_line = None
        self._streaming_box_top_line = None
        self._streaming_box_config = None
        self._streaming_box_command = ""
        self._streaming_box_working_dir = "."
        self._streaming_box_content_lines = []

    def _rebuild_streaming_box_as_collapsed(
        self,
        is_error: bool,
        content_lines: list[str],
    ) -> None:
        if self._streaming_box_top_line is None:
            return

        self._truncate_from(self._streaming_box_top_line)

        start_line = len(self.log.lines)

        summary = summarize_output(content_lines, "bash")
        hint = get_expansion_hint()
        summary_line = Text("  \u23bf  ", style=GREY)
        summary_line.append(summary, style=SUBTLE)
        summary_line.append(f" {hint}", style=f"{SUBTLE} italic")
        self.log.write(summary_line, wrappable=False)

        end_line = len(self.log.lines) - 1

        collapsible = CollapsibleOutput(
            start_line=start_line,
            end_line=end_line,
            full_content=content_lines,
            summary=summary,
            is_expanded=False,
            output_type="bash",
            command=self._streaming_box_command,
            working_dir=self._streaming_box_working_dir,
            is_error=is_error,
            depth=0,
        )
        self._collapsible_outputs[start_line] = collapsible
        self._most_recent_collapsible = start_line

    def toggle_most_recent_collapsible(self) -> bool:
        if self._most_recent_collapsible is None:
            return False
        collapsible = self._collapsible_outputs.get(self._most_recent_collapsible)
        if collapsible is None:
            return False
        return self._toggle_collapsible(collapsible)

    def toggle_output_at_line(self, line_index: int) -> bool:
        for start, collapsible in self._collapsible_outputs.items():
            if collapsible.contains_line(line_index):
                return self._toggle_collapsible(collapsible)
        return False

    def _toggle_collapsible(self, collapsible: CollapsibleOutput) -> bool:
        if collapsible.is_expanded:
            self._collapse_output(collapsible)
        else:
            self._expand_output(collapsible)
        return True

    def _expand_output(self, collapsible: CollapsibleOutput) -> None:
        self._truncate_from(collapsible.start_line)
        indent = "  " * collapsible.depth
        new_start = len(self.log.lines)

        is_first = True
        for line in collapsible.full_content:
            self._write_bash_output_line(line, indent, collapsible.is_error, is_first)
            is_first = False

        collapsible.is_expanded = True
        new_end = len(self.log.lines) - 1

        if collapsible.start_line in self._collapsible_outputs:
            del self._collapsible_outputs[collapsible.start_line]
        collapsible.start_line = new_start
        collapsible.end_line = new_end
        self._collapsible_outputs[new_start] = collapsible
        self._most_recent_collapsible = new_start

        self.log.refresh()

    def _collapse_output(self, collapsible: CollapsibleOutput) -> None:
        self._truncate_from(collapsible.start_line)
        indent = "  " * collapsible.depth
        new_start = len(self.log.lines)

        hint = get_expansion_hint()
        summary_line = Text(f"{indent}  \u23bf  ", style=GREY)
        summary_line.append(collapsible.summary, style=SUBTLE)
        summary_line.append(f" {hint}", style=f"{SUBTLE} italic")
        self.log.write(summary_line, wrappable=False)

        collapsible.is_expanded = False
        new_end = len(self.log.lines) - 1

        if collapsible.start_line in self._collapsible_outputs:
            del self._collapsible_outputs[collapsible.start_line]
        collapsible.start_line = new_start
        collapsible.end_line = new_end
        self._collapsible_outputs[new_start] = collapsible
        self._most_recent_collapsible = new_start

        self.log.refresh()

    def has_collapsible_output(self) -> bool:
        return len(self._collapsible_outputs) > 0

    def get_collapsible_at_line(self, line_index: int) -> Optional[CollapsibleOutput]:
        for collapsible in self._collapsible_outputs.values():
            if collapsible.contains_line(line_index):
                return collapsible
        return None

    def add_nested_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = "",
        depth: int = 1,
    ) -> None:
        self.add_bash_output_box(output, is_error, command, working_dir, depth)

    # --- Nested Tool Result Display Methods ---

    def add_todo_sub_result(self, text: str, depth: int, is_last_parent: bool = True) -> None:
        formatted = Text()
        indent = "  " * depth
        formatted.append(indent)
        formatted.append("  ⎿  ", style=GREY)
        formatted.append(text, style=SUBTLE)
        self.log.write(formatted, scroll_end=True, animate=False, wrappable=False)

    def add_todo_sub_results(self, items: list, depth: int, is_last_parent: bool = True) -> None:
        indent = "  " * depth
        for i, (symbol, title) in enumerate(items):
            formatted = Text()
            formatted.append(indent)
            prefix = "  ⎿  " if i == 0 else "     "
            formatted.append(prefix, style=GREY)
            formatted.append(f"{symbol} {title}", style=SUBTLE)
            self.log.write(formatted, scroll_end=True, animate=False, wrappable=False)

    def add_nested_tool_sub_results(
        self, lines: List[str], depth: int, is_last_parent: bool = True
    ) -> None:
        indent = "  " * depth

        all_lines = []
        for line in lines:
            if "\n" in line:
                all_lines.extend(line.split("\n"))
            else:
                all_lines.append(line)

        while all_lines and not all_lines[-1].strip():
            all_lines.pop()

        non_empty_lines = [(i, line) for i, line in enumerate(all_lines) if line.strip()]

        has_error = any(TOOL_ERROR_SENTINEL in line for _, line in non_empty_lines)
        has_interrupted = any("::interrupted::" in line for _, line in non_empty_lines)

        for idx, (orig_i, line) in enumerate(non_empty_lines):
            formatted = Text()
            formatted.append(indent)

            prefix = "  ⎿  " if idx == 0 else "     "
            formatted.append(prefix, style=GREY)

            clean_line = (
                line.replace(TOOL_ERROR_SENTINEL, "").replace("::interrupted::", "").strip()
            )
            import re
            clean_line = re.sub(r"\x1b\[[0-9;]*m", "", clean_line)

            if has_interrupted:
                formatted.append(clean_line, style=f"bold {ERROR}")
            elif has_error:
                formatted.append(clean_line, style=ERROR)
            else:
                formatted.append(clean_line, style=SUBTLE)

            self.log.write(formatted, scroll_end=True, animate=False, wrappable=False)

    def add_nested_tree_result(
        self,
        tool_outputs: List[str],
        depth: int,
        is_last_parent: bool = True,
        has_error: bool = False,
        has_interrupted: bool = False,
    ) -> None:
        self.add_nested_tool_sub_results(tool_outputs, depth, is_last_parent)

    def add_edit_diff_result(self, diff_text: str, depth: int, is_last_parent: bool = True) -> None:
        from swecli.ui_textual.formatters_internal.utils import DiffParser

        diff_entries = DiffParser.parse_unified_diff(diff_text)
        if not diff_entries:
            return

        indent = "  " * depth
        hunks = DiffParser.group_by_hunk(diff_entries)
        total_hunks = len(hunks)

        line_idx = 0

        for hunk_idx, (start_line, hunk_entries) in enumerate(hunks):
            if total_hunks > 1:
                if hunk_idx > 0:
                    self.log.write(Text(""), scroll_end=True, animate=False, wrappable=False)

                formatted = Text()
                formatted.append(indent)
                prefix = "  ⎿  " if line_idx == 0 else "     "
                formatted.append(prefix, style=GREY)
                formatted.append(
                    f"[Edit {hunk_idx + 1}/{total_hunks} at line {start_line}]", style=CYAN
                )
                self.log.write(formatted, scroll_end=True, animate=False, wrappable=False)
                line_idx += 1

            for entry_type, line_no, content in hunk_entries:
                formatted = Text()
                formatted.append(indent)

                prefix = "  ⎿  " if line_idx == 0 else "     "
                formatted.append(prefix, style=GREY)

                if entry_type == "add":
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

                self.log.write(formatted, scroll_end=True, animate=False, wrappable=False)
                line_idx += 1
