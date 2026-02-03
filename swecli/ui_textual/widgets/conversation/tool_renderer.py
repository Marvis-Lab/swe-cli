from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from rich.text import Text
from textual.strip import Strip
from textual.timer import Timer

from swecli.ui_textual.constants import TOOL_ERROR_SENTINEL
from swecli.ui_textual.style_tokens import (
    CYAN,
    ERROR,
    GREEN_BRIGHT,
    GREY,
    PRIMARY,
    SUBTLE,
)
from swecli.ui_textual.widgets.terminal_box_renderer import (
    TerminalBoxConfig,
    TerminalBoxRenderer,
)
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager
from swecli.ui_textual.models.collapsible_output import CollapsibleOutput
from swecli.ui_textual.utils.output_summarizer import summarize_output, get_expansion_hint

# Import models and renderers
from swecli.ui_textual.widgets.conversation.renderers.models import (
    AgentInfo,
    AgentStats,
    NestedToolState,
    ParallelAgentGroup,
    SingleAgentInfo,
)
from swecli.ui_textual.widgets.conversation.renderers.nested_tool_renderer import NestedToolRenderer
from swecli.ui_textual.widgets.conversation.renderers.parallel_agent_renderer import ParallelAgentRenderer
from swecli.ui_textual.widgets.conversation.renderers.single_agent_renderer import SingleAgentRenderer
from swecli.ui_textual.widgets.conversation.renderers.utils import (
    TREE_BRANCH,
    TREE_CONTINUATION,
    TREE_LAST,
    TREE_VERTICAL,
)


class DefaultToolRenderer:
    """Handles rendering of tool calls, results, and nested execution animations."""

    def __init__(self, log: RichLogInterface, app_callback_interface: Any = None):
        self.log = log
        self.app = app_callback_interface
        self._spacing = SpacingManager(log)

        # Initialize sub-renderers
        self._nested_renderer = NestedToolRenderer(log, self._spacing)
        self._parallel_renderer = ParallelAgentRenderer(log, self._spacing)
        self._single_renderer = SingleAgentRenderer(log, self._spacing)

        # Tool execution state (Standard tools)
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
        self._nested_tool_timer: Timer | None = None

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

    # --- Properties for Backward Compatibility / Test Support ---

    @property
    def _parallel_group(self) -> Optional[ParallelAgentGroup]:
        return self._parallel_renderer.parallel_group

    @_parallel_group.setter
    def _parallel_group(self, value: Optional[ParallelAgentGroup]):
        self._parallel_renderer._parallel_group = value

    @property
    def _parallel_expanded(self) -> bool:
        return self._parallel_renderer.parallel_expanded

    @_parallel_expanded.setter
    def _parallel_expanded(self, value: bool):
        self._parallel_renderer._parallel_expanded = value

    @property
    def _single_agent(self) -> Optional[SingleAgentInfo]:
        return self._single_renderer.single_agent

    @_single_agent.setter
    def _single_agent(self, value: Optional[SingleAgentInfo]):
        self._single_renderer._single_agent = value

    @property
    def _nested_tools(self) -> Dict[Tuple[str, str], NestedToolState]:
        return self._nested_renderer._nested_tools

    @property
    def _nested_tool_line(self) -> Optional[int]:
        return self._nested_renderer._nested_tool_line

    @_nested_tool_line.setter
    def _nested_tool_line(self, value: Optional[int]):
        self._nested_renderer._nested_tool_line = value

    @property
    def _nested_tool_text(self) -> Optional[Text]:
        return self._nested_renderer._nested_tool_text

    @_nested_tool_text.setter
    def _nested_tool_text(self, value: Optional[Text]):
        self._nested_renderer._nested_tool_text = value

    # --- Methods ---

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
        self._nested_renderer.adjust_indices(delta, first_affected)
        self._parallel_renderer.adjust_indices(delta, first_affected)
        self._single_renderer.adjust_indices(delta, first_affected)

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

        self._most_recent_collapsible = adj(self._most_recent_collapsible)

    def resume_after_resize(self) -> None:
        """Restart animations after resize."""
        self._paused_for_resize = False

        has_active = (
            self._nested_renderer.has_active_tools
            or self._parallel_renderer.has_active_parallel_group()
            or (self._single_renderer.single_agent is not None and self._single_renderer.single_agent.status == "running")
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

        def text_to_strip(text: Text) -> "Strip":
            from rich.console import Console
            from textual.strip import Strip
            console = Console(width=1000, force_terminal=True, no_color=False)
            segments = list(text.render(console))
            return Strip(segments)

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
        if isinstance(display, Text):
            tool_text = display.copy()
        else:
            tool_text = Text(str(display), style=SUBTLE)

        # 1. Single Agent Check
        if self._single_renderer.single_agent is not None and self._single_renderer.single_agent.status == "running":
            plain_text = tool_text.plain if hasattr(tool_text, "plain") else str(tool_text)
            if ":" in plain_text:
                tool_name = plain_text.split(":")[0].strip()
            elif "(" in plain_text:
                tool_name = plain_text.split("(")[0].strip()
            else:
                tool_name = plain_text.split()[0] if plain_text.split() else "unknown"

            agent = self._single_renderer.single_agent
            agent.tool_count += 1
            agent.current_tool = plain_text

            # Trigger updates via private/public methods of SingleAgentRenderer
            # Note: _update_header_spinner is updated in animation loop, but we can call it here if needed.
            # But the logic usually just updates model and waits for animation?
            # Original code called _update_header_spinner() immediately.
            self._single_renderer._update_header_spinner()
            self._single_renderer._update_single_agent_status_line()
            self._single_renderer.update_single_agent_tool_line()
            return

        # 2. Parallel Agent Check
        if self._parallel_renderer.parallel_group is not None:
            agent = self._parallel_renderer.parallel_group.agents.get(parent)
            if agent is not None:
                plain_text = tool_text.plain if hasattr(tool_text, "plain") else str(tool_text)
                if ":" in plain_text:
                    tool_name = plain_text.split(":")[0].strip()
                elif "(" in plain_text:
                    tool_name = plain_text.split("(")[0].strip()
                else:
                    tool_name = plain_text.split()[0] if plain_text.split() else "unknown"

                agent.tool_count += 1
                agent.current_tool = plain_text

                self._parallel_renderer.update_agent_row(agent)
                self._parallel_renderer.update_status_line(agent)

                if not self._parallel_renderer.parallel_expanded:
                    return

        # 3. Standard Nested Tool Call
        self._nested_renderer.add_nested_tool_call(display, depth, parent, tool_id, is_last)
        self._start_nested_tool_timer()

    def complete_nested_tool_call(
        self,
        tool_name: str,
        depth: int,
        parent: str,
        success: bool,
        tool_id: str = "",
    ) -> None:
        self._nested_renderer.complete_nested_tool_call(tool_name, depth, parent, success, tool_id)

        # Stop timers only if no more active tools
        if not self._nested_renderer.has_active_tools:
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
            self._nested_renderer.has_active_tools
            or self._parallel_renderer.has_active_parallel_group()
            or (self._single_renderer.single_agent is not None and self._single_renderer.single_agent.status == "running")
        )

        if not has_active:
            self._nested_tool_timer = None
            return

        # Animate sub-renderers
        self._nested_renderer.animate()
        self._parallel_renderer.animate()
        self._single_renderer.animate()

        interval = 0.15
        self._nested_tool_timer = self.log.set_timer(interval, self._animate_nested_tool_spinner)
        self._nested_tool_thread_timer = threading.Timer(interval, self._on_nested_tool_thread_tick)
        self._nested_tool_thread_timer.daemon = True
        self._nested_tool_thread_timer.start()

    def _on_nested_tool_thread_tick(self) -> None:
        # Check active status
        has_active = (
            self._nested_renderer.has_active_tools
            or self._nested_renderer._nested_tool_line is not None
        )
        if not has_active:
             return
        try:
            if self.app:
                self.app.call_from_thread(self._animate_nested_tool_spinner)
        except Exception:
            pass

    # --- Delegated Methods ---

    def on_parallel_agents_start(self, agent_infos: List[dict]) -> None:
        self._parallel_renderer.on_parallel_agents_start(agent_infos)
        self._start_nested_tool_timer()

    def on_parallel_agent_complete(self, tool_call_id: str, success: bool) -> None:
        self._parallel_renderer.on_parallel_agent_complete(tool_call_id, success)

    def on_parallel_agents_done(self) -> None:
        self._parallel_renderer.on_parallel_agents_done()

    def toggle_parallel_expansion(self) -> bool:
        return self._parallel_renderer.toggle_parallel_expansion()

    def has_active_parallel_group(self) -> bool:
        return self._parallel_renderer.has_active_parallel_group()

    def on_single_agent_start(self, agent_type: str, description: str, tool_call_id: str) -> None:
        self._single_renderer.on_single_agent_start(agent_type, description, tool_call_id)
        self._start_nested_tool_timer()

    def on_single_agent_complete(self, tool_call_id: str, success: bool = True) -> None:
        self._single_renderer.on_single_agent_complete(tool_call_id, success)

    def add_todo_sub_result(self, text: str, depth: int, is_last_parent: bool = True) -> None:
        self._nested_renderer.add_todo_sub_result(text, depth, is_last_parent)

    def add_todo_sub_results(self, items: list, depth: int, is_last_parent: bool = True) -> None:
        self._nested_renderer.add_todo_sub_results(items, depth, is_last_parent)

    def add_nested_tool_sub_results(
        self, lines: List[str], depth: int, is_last_parent: bool = True
    ) -> None:
        self._nested_renderer.add_nested_tool_sub_results(lines, depth, is_last_parent)

    def add_nested_tree_result(
        self,
        tool_outputs: List[str],
        depth: int,
        is_last_parent: bool = True,
        has_error: bool = False,
        has_interrupted: bool = False,
    ) -> None:
        self._nested_renderer.add_nested_tree_result(
            tool_outputs, depth, is_last_parent, has_error, has_interrupted
        )

    def add_edit_diff_result(self, diff_text: str, depth: int, is_last_parent: bool = True) -> None:
        self._nested_renderer.add_edit_diff_result(diff_text, depth, is_last_parent)

    def add_nested_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = "",
        depth: int = 1,
    ) -> None:
        self.add_bash_output_box(output, is_error, command, working_dir, depth)

    # --- Tool Call Rendering Internal ---

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
        if self.app and hasattr(self.app, "refresh"):
            self.app.refresh()

    def _write_tool_call_line(self, prefix: str) -> None:
        formatted = Text()
        formatted.append(f"{prefix} ", style=GREEN_BRIGHT)
        if self._tool_display:
            formatted.append_text(self._tool_display)
        formatted.append(" (0s)", style=GREY)
        self.log.write(formatted, wrappable=False)

    # --- Helpers ---

    def _extract_edit_payload(self, text: str) -> Tuple[str, List[str]]:
        lines = text.splitlines()
        if not lines:
            return "", []

        header = ""
        diff_lines = []

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

    # --- Bash Box Output (Delegated to local methods but can be refactored) ---

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
