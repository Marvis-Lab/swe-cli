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
    ERROR,
    GREY,
    PRIMARY,
    SUBTLE,
    GREEN_BRIGHT,
)
from swecli.ui_textual.widgets.terminal_box_renderer import (
    TerminalBoxConfig,
    TerminalBoxRenderer,
)
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager
from swecli.ui_textual.models.collapsible_output import CollapsibleOutput
from swecli.ui_textual.utils.output_summarizer import summarize_output, get_expansion_hint

from swecli.ui_textual.widgets.conversation.renderers.models import (
    AgentInfo,
    SingleAgentInfo,
    ParallelAgentGroup,
    NestedToolState,
    AgentStats,
)
from swecli.ui_textual.widgets.conversation.renderers.parallel_agent_renderer import ParallelAgentRenderer
from swecli.ui_textual.widgets.conversation.renderers.single_agent_renderer import SingleAgentRenderer
from swecli.ui_textual.widgets.conversation.renderers.nested_tool_renderer import NestedToolRenderer
from swecli.ui_textual.widgets.conversation.renderers.utils import text_to_strip


class DefaultToolRenderer:
    """Handles rendering of tool calls, results, and nested execution animations."""

    def __init__(self, log: RichLogInterface, app_callback_interface: Any = None):
        self.log = log
        self.app = app_callback_interface
        self._spacing = SpacingManager(log)

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

        # Sub-renderers
        self.parallel_renderer = ParallelAgentRenderer(log, self._spacing)
        self.single_renderer = SingleAgentRenderer(log, self._spacing)
        self.nested_renderer = NestedToolRenderer(log, self._spacing)

        # Animation timer for nested/agent animations
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
            """Adjust a single index if affected."""
            return idx + delta if idx is not None and idx >= first_affected else idx

        # Adjust tool call tracking
        self._tool_call_start = adj(self._tool_call_start)

        # Adjust sub-renderers
        self.parallel_renderer.adjust_indices(delta, first_affected)
        self.single_renderer.adjust_indices(delta, first_affected)
        self.nested_renderer.adjust_indices(delta, first_affected)

        # Adjust streaming box lines
        self._streaming_box_header_line = adj(self._streaming_box_header_line)
        self._streaming_box_top_line = adj(self._streaming_box_top_line)

        # Adjust collapsible outputs (rebuild dict with new keys)
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

        # Check if there are any active animations that need to be restarted
        has_active = (
            self.nested_renderer.has_active_tools()
            or self.parallel_renderer.has_running_agents()
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
        """Add a tool result to the log."""
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
        """Add continuation lines for tool result."""
        if not lines:
            return

        # Check if we have a pending spacing line to overwrite
        spacing_line = getattr(self.log, "_pending_spacing_line", None)

        for i, line in enumerate(lines):
            formatted = Text("     ", style=GREY)  # 5 spaces to align with ⎿ content
            formatted.append(line, style=SUBTLE)

            if i == 0 and spacing_line is not None and spacing_line < len(self.log.lines):
                # Overwrite spacing placeholder with first diff line (no gap)
                self.log.lines[spacing_line] = text_to_strip(formatted)
            else:
                # Tool result continuation lines preserve formatting, don't re-wrap
                self.log.write(formatted, wrappable=False)

        # Clear the pending spacing line
        self.log._pending_spacing_line = None

        # Add blank line at end for spacing before next tool
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
        """Add a nested tool call with multi-tool tracking support."""
        if isinstance(display, Text):
            tool_text = display.copy()
        else:
            tool_text = Text(str(display), style=SUBTLE)

        plain_text = tool_text.plain if hasattr(tool_text, "plain") else str(tool_text)
        if ":" in plain_text:
            tool_name = plain_text.split(":")[0].strip()
        elif "(" in plain_text:
            tool_name = plain_text.split("(")[0].strip()
        else:
            tool_name = plain_text.split()[0] if plain_text.split() else "unknown"

        # Delegate to single agent renderer
        if self.single_renderer.has_active_agent():
            self.single_renderer.on_tool_call(plain_text)
            self._start_nested_tool_timer()
            return

        # Delegate to parallel agent renderer
        if self.parallel_renderer.has_active_group():
            # In parallel renderer, 'parent' is expected to be tool_call_id
            self.parallel_renderer.update_agent_tool(parent, plain_text)

            # If collapsed, don't render individual tool
            if not self.parallel_renderer.expanded:
                self._start_nested_tool_timer()
                return

        # Delegate to nested tool renderer (expanded parallel or normal nested)
        self.nested_renderer.add_nested_tool_call(display, depth, parent, tool_id, is_last)
        self._start_nested_tool_timer()

    def complete_nested_tool_call(
        self,
        tool_name: str,
        depth: int,
        parent: str,
        success: bool,
        tool_id: str = "",
    ) -> None:
        """Complete a nested tool call, updating the display."""
        # Stop timers only if no more active tools (checked inside renderer/animation loop usually)
        # But we need to ensure timers stop if everything is done.

        self.nested_renderer.complete_nested_tool_call(tool_name, depth, parent, success, tool_id)

        # Stop timers if no active animations
        has_active = (
            self.nested_renderer.has_active_tools()
            or self.parallel_renderer.has_running_agents()
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
        """Start or continue the nested tool animation timer."""
        # Only start timer if not already running
        if self._nested_tool_timer is None:
            self._animate_nested_tool_spinner()

    def _animate_nested_tool_spinner(self) -> None:
        """Animate ALL active nested tool spinners AND agent row spinners."""
        if self._paused_for_resize:
            return  # Skip animation during resize

        if self._nested_tool_thread_timer:
            self._nested_tool_thread_timer.cancel()
            self._nested_tool_thread_timer = None

        has_active = (
            self.nested_renderer.has_active_tools()
            or self.parallel_renderer.has_running_agents()
            or self.single_renderer.has_active_agent()
        )

        if not has_active:
            self._nested_tool_timer = None
            return

        # Delegate animation frames
        self.nested_renderer.animate()
        self.parallel_renderer.animate()
        self.single_renderer.animate()

        # Schedule next animation frame
        interval = 0.15
        self._nested_tool_timer = self.log.set_timer(interval, self._animate_nested_tool_spinner)
        self._nested_tool_thread_timer = threading.Timer(interval, self._on_nested_tool_thread_tick)
        self._nested_tool_thread_timer.daemon = True
        self._nested_tool_thread_timer.start()

    def _on_nested_tool_thread_tick(self) -> None:
        """Thread timer callback for nested tool animation."""
        has_active = (
            self.nested_renderer.has_active_tools()
            or self.parallel_renderer.has_running_agents()
            or self.single_renderer.has_active_agent()
        )
        if not has_active:
            return
        try:
            if self.app:
                self.app.call_from_thread(self._animate_nested_tool_spinner)
        except Exception:
            pass

    # --- Parallel Agent Group Management ---

    def on_parallel_agents_start(self, agent_infos: List[dict]) -> None:
        """Called when parallel agents start executing."""
        self.parallel_renderer.on_parallel_agents_start(agent_infos)
        self._start_nested_tool_timer()

    def on_parallel_agent_complete(self, tool_call_id: str, success: bool) -> None:
        """Called when a parallel agent completes."""
        self.parallel_renderer.on_parallel_agent_complete(tool_call_id, success)

    def on_parallel_agents_done(self) -> None:
        """Called when all parallel agents have completed."""
        self.parallel_renderer.on_parallel_agents_done()

    def toggle_parallel_expansion(self) -> bool:
        """Toggle the expand/collapse state of parallel agent display."""
        return self.parallel_renderer.toggle_expansion()

    def has_active_parallel_group(self) -> bool:
        """Check if there's an active parallel agent group."""
        return self.parallel_renderer.has_active_group()

    # --- Single Agent Management ---

    def on_single_agent_start(self, agent_type: str, description: str, tool_call_id: str) -> None:
        """Called when a single agent starts (non-parallel execution)."""
        self.single_renderer.on_single_agent_start(agent_type, description, tool_call_id)
        self._start_nested_tool_timer()

    def on_single_agent_complete(self, tool_call_id: str, success: bool = True) -> None:
        """Called when a single agent completes."""
        self.single_renderer.on_single_agent_complete(tool_call_id, success)

    # --- Bash Box Output ---

    def add_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = ".",
        depth: int = 0,
    ) -> None:
        """Render bash output with collapsible support for long output."""
        lines = output.rstrip("\n").splitlines()

        # Apply truncation based on depth
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
            # Store full content and render collapsed summary
            start_line = len(self.log.lines)

            # Write collapsed summary line - summary text can wrap
            summary = summarize_output(lines, "bash")
            hint = get_expansion_hint()
            summary_line = Text(f"{indent}  \u23bf  ", style=GREY)
            summary_line.append(summary, style=SUBTLE)
            summary_line.append(f" {hint}", style=f"{SUBTLE} italic")
            self.log.write(summary_line, wrappable=False)

            end_line = len(self.log.lines) - 1

            # Track collapsible region
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
            # Small output - render normally without collapse
            is_first = True
            for line in lines:
                self._write_bash_output_line(line, indent, is_error, is_first)
                is_first = False

        # Add blank line for spacing after output
        self._spacing.after_bash_output_box()

    def _write_bash_output_line(
        self, line: str, indent: str, is_error: bool, is_first: bool = False
    ) -> None:
        """Write a single bash output line with proper indentation."""
        normalized = self._box_renderer.normalize_line(line)
        # Use ⎿ prefix for first line, spaces for rest
        prefix = f"{indent}  \u23bf  " if is_first else f"{indent}     "
        output_line = Text(prefix, style=GREY)
        output_line.append(normalized, style=ERROR if is_error else GREY)
        # Bash output preserves formatting, don't re-wrap
        self.log.write(output_line, wrappable=False)

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
        """Close streaming bash output, collapsing if it exceeds threshold."""
        content_lines = [line for line, _ in self._streaming_box_content_lines]
        head_count = self._box_renderer.MAIN_AGENT_HEAD_LINES
        tail_count = self._box_renderer.MAIN_AGENT_TAIL_LINES
        max_lines = head_count + tail_count

        if len(content_lines) > max_lines and self._streaming_box_top_line is not None:
            # Rebuild with collapsed summary instead of truncation
            self._rebuild_streaming_box_as_collapsed(is_error, content_lines)

        # Reset state
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
        """Rebuild streaming output as a collapsed summary."""
        if self._streaming_box_top_line is None:
            return

        # Remove all lines from top of output to current position
        self._truncate_from(self._streaming_box_top_line)

        start_line = len(self.log.lines)

        # Write collapsed summary line - don't re-wrap
        summary = summarize_output(content_lines, "bash")
        hint = get_expansion_hint()
        summary_line = Text("  \u23bf  ", style=GREY)
        summary_line.append(summary, style=SUBTLE)
        summary_line.append(f" {hint}", style=f"{SUBTLE} italic")
        self.log.write(summary_line, wrappable=False)

        end_line = len(self.log.lines) - 1

        # Track collapsible region
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

    # --- Collapsible Output Toggle Methods ---

    def toggle_most_recent_collapsible(self) -> bool:
        """Toggle the most recent collapsible output region."""
        if self._most_recent_collapsible is None:
            return False

        collapsible = self._collapsible_outputs.get(self._most_recent_collapsible)
        if collapsible is None:
            return False

        return self._toggle_collapsible(collapsible)

    def toggle_output_at_line(self, line_index: int) -> bool:
        """Toggle collapsible output containing the given line."""
        # Find collapsible region containing this line
        for start, collapsible in self._collapsible_outputs.items():
            if collapsible.contains_line(line_index):
                return self._toggle_collapsible(collapsible)
        return False

    def _toggle_collapsible(self, collapsible: CollapsibleOutput) -> bool:
        """Toggle a specific collapsible output region."""
        if collapsible.is_expanded:
            self._collapse_output(collapsible)
        else:
            self._expand_output(collapsible)
        return True

    def _expand_output(self, collapsible: CollapsibleOutput) -> None:
        """Expand a collapsed output region to show full content."""
        # Remove the summary line(s)
        self._truncate_from(collapsible.start_line)

        indent = "  " * collapsible.depth
        new_start = len(self.log.lines)

        # Render full content
        is_first = True
        for line in collapsible.full_content:
            self._write_bash_output_line(line, indent, collapsible.is_error, is_first)
            is_first = False

        # Update collapsible state
        collapsible.is_expanded = True
        new_end = len(self.log.lines) - 1

        # Update tracking (move to new position if changed)
        if collapsible.start_line in self._collapsible_outputs:
            del self._collapsible_outputs[collapsible.start_line]
        collapsible.start_line = new_start
        collapsible.end_line = new_end
        self._collapsible_outputs[new_start] = collapsible
        self._most_recent_collapsible = new_start

        self.log.refresh()

    def _collapse_output(self, collapsible: CollapsibleOutput) -> None:
        """Collapse an expanded output region to show just summary."""
        # Remove the expanded content
        self._truncate_from(collapsible.start_line)

        indent = "  " * collapsible.depth
        new_start = len(self.log.lines)

        # Write collapsed summary - don't re-wrap
        hint = get_expansion_hint()
        summary_line = Text(f"{indent}  \u23bf  ", style=GREY)
        summary_line.append(collapsible.summary, style=SUBTLE)
        summary_line.append(f" {hint}", style=f"{SUBTLE} italic")
        self.log.write(summary_line, wrappable=False)

        # Update collapsible state
        collapsible.is_expanded = False
        new_end = len(self.log.lines) - 1

        # Update tracking
        if collapsible.start_line in self._collapsible_outputs:
            del self._collapsible_outputs[collapsible.start_line]
        collapsible.start_line = new_start
        collapsible.end_line = new_end
        self._collapsible_outputs[new_start] = collapsible
        self._most_recent_collapsible = new_start

        self.log.refresh()

    def has_collapsible_output(self) -> bool:
        """Check if there are any collapsible output regions."""
        return len(self._collapsible_outputs) > 0

    def get_collapsible_at_line(self, line_index: int) -> Optional[CollapsibleOutput]:
        """Get collapsible output at a specific line."""
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
        """Render nested bash output with minimal style."""
        # Use the same add_bash_output_box with depth parameter
        self.add_bash_output_box(output, is_error, command, working_dir, depth)

    # --- Nested Tool Result Display Methods ---

    def add_todo_sub_result(self, text: str, depth: int, is_last_parent: bool = True) -> None:
        """Add a single sub-result line for todo operations."""
        self.nested_renderer.add_todo_sub_result(text, depth, is_last_parent)

    def add_todo_sub_results(self, items: list, depth: int, is_last_parent: bool = True) -> None:
        """Add multiple sub-result lines for todo list operations."""
        self.nested_renderer.add_todo_sub_results(items, depth, is_last_parent)

    def add_nested_tool_sub_results(
        self, lines: List[str], depth: int, is_last_parent: bool = True
    ) -> None:
        """Add tool result lines with proper nesting indentation."""
        self.nested_renderer.add_nested_tool_sub_results(lines, depth, is_last_parent)

    def add_nested_tree_result(
        self,
        tool_outputs: List[str],
        depth: int,
        is_last_parent: bool = True,
        has_error: bool = False,
        has_interrupted: bool = False,
    ) -> None:
        """Add tool result with tree-style indentation (legacy support)."""
        self.nested_renderer.add_nested_tree_result(
            tool_outputs, depth, is_last_parent, has_error, has_interrupted
        )

    def add_edit_diff_result(self, diff_text: str, depth: int, is_last_parent: bool = True) -> None:
        """Add diff lines for edit_file result in subagent output."""
        self.nested_renderer.add_edit_diff_result(diff_text, depth, is_last_parent)

    def _truncate_from(self, index: int) -> None:
        if index >= len(self.log.lines):
            return

        # Access protected lines from log if available
        protected_lines = getattr(self.log, "_protected_lines", set())

        # Check if any protected lines would be affected
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

        strip = text_to_strip(formatted)

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
