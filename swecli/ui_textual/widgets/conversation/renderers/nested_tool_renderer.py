from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Tuple, Any

from rich.text import Text
from textual.strip import Strip
from rich.console import Console

from swecli.ui_textual.style_tokens import (
    CYAN,
    ERROR,
    GREEN_BRIGHT,
    GREEN_GRADIENT,
    GREY,
    PRIMARY,
    SUBTLE,
    SUCCESS,
)
from swecli.ui_textual.constants import TOOL_ERROR_SENTINEL
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.renderers.models import NestedToolState
from swecli.ui_textual.widgets.conversation.renderers.utils import (
    TREE_BRANCH,
    TREE_CONTINUATION,
    TREE_LAST,
    TREE_VERTICAL,
    text_to_strip,
)
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager


class NestedToolRenderer:
    """Renderer for nested tool calls (tree structure)."""

    def __init__(self, log: RichLogInterface, spacing: SpacingManager):
        self.log = log
        self._spacing = spacing

        # State
        self._nested_tools: Dict[Tuple[str, str], NestedToolState] = {}
        self._nested_spinner_char = "⏺"

        # Legacy single-tool state
        self._nested_tool_line: Optional[int] = None
        self._nested_tool_text: Optional[Text] = None
        self._nested_tool_depth: int = 1
        self._nested_color_index = 0
        self._nested_tool_timer_start: Optional[float] = None

    def add_nested_tool_call(
        self,
        display: Text | str,
        depth: int,
        parent: str,
        tool_id: str = "",
        is_last: bool = False,
    ) -> None:
        """Add a nested tool call."""
        if isinstance(display, Text):
            tool_text = display.copy()
        else:
            tool_text = Text(str(display), style=SUBTLE)

        self._spacing.before_nested_tool_call()

        formatted = Text()
        indent = self._build_tree_indent(depth, parent, is_last)
        formatted.append(indent)
        formatted.append(f"{self._nested_spinner_char} ", style=GREEN_GRADIENT[0])
        formatted.append_text(tool_text)
        formatted.append(" (0s)", style=GREY)

        self.log.write(formatted, scroll_end=True, animate=False, wrappable=False)

        if not tool_id:
            tool_id = f"{parent}_{len(self._nested_tools)}_{time.monotonic()}"

        key = (parent, tool_id)
        self._nested_tools[key] = NestedToolState(
            line_number=len(self.log.lines) - 1,
            tool_text=tool_text.copy(),
            depth=depth,
            timer_start=time.monotonic(),
            color_index=0,
            parent=parent,
            tool_id=tool_id,
        )

        # Legacy state update
        self._nested_tool_line = len(self.log.lines) - 1
        self._nested_tool_text = tool_text.copy()
        self._nested_tool_depth = depth
        self._nested_color_index = 0
        self._nested_tool_timer_start = time.monotonic()

    def complete_nested_tool_call(
        self,
        tool_name: str,
        depth: int,
        parent: str,
        success: bool,
        tool_id: str = "",
    ) -> None:
        """Complete a nested tool call."""
        state: Optional[NestedToolState] = None

        if tool_id:
            key = (parent, tool_id)
            state = self._nested_tools.pop(key, None)

        if state is None:
            # Fallback: find most recent for parent
            for key in list(self._nested_tools.keys()):
                if key[0] == parent:
                    state = self._nested_tools.pop(key)
                    break

        if state is None:
            # Legacy fallback
            if self._nested_tool_line is not None and self._nested_tool_text is not None:
                state = NestedToolState(
                    line_number=self._nested_tool_line,
                    tool_text=self._nested_tool_text,
                    depth=self._nested_tool_depth,
                    timer_start=self._nested_tool_timer_start or time.monotonic(),
                    parent=parent,
                )
                self._nested_tool_line = None
                self._nested_tool_text = None
                self._nested_tool_timer_start = None
            else:
                return

        # If no more tools are tracked in the dict, clear legacy state as well
        # to ensure has_active_tools returns False
        if not self._nested_tools:
            self._nested_tool_line = None
            self._nested_tool_text = None
            self._nested_tool_timer_start = None

        formatted = Text()
        indent = self._build_tree_indent(state.depth, state.parent, is_last=False)
        formatted.append(indent)

        status_char = "✓" if success else "✗"
        status_color = SUCCESS if success else ERROR

        formatted.append(f"{status_char} ", style=status_color)
        formatted.append_text(state.tool_text)

        elapsed = round(time.monotonic() - state.timer_start)
        formatted.append(f" ({elapsed}s)", style=GREY)

        strip = text_to_strip(formatted)

        if state.line_number < len(self.log.lines):
            self.log.lines[state.line_number] = strip
            self.log.refresh_line(state.line_number)

    def has_active_tools(self) -> bool:
        return bool(self._nested_tools) or (self._nested_tool_line is not None)

    def animate(self) -> None:
        """Perform one frame of animation."""
        # Animate all tools in dict
        for key, state in self._nested_tools.items():
            state.color_index = (state.color_index + 1) % len(GREEN_GRADIENT)
            self._render_nested_tool_line_for_state(state)

        # Animate legacy
        if self._nested_tool_line is not None and self._nested_tool_text is not None:
            self._nested_color_index = (self._nested_color_index + 1) % len(GREEN_GRADIENT)
            self._render_nested_tool_line()

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        """Adjust line indices after resize."""
        self._nested_tool_line = self._adj(self._nested_tool_line, delta, first_affected)

        for state in self._nested_tools.values():
            if state.line_number >= first_affected:
                state.line_number += delta

    def _adj(self, idx: Optional[int], delta: int, first_affected: int) -> Optional[int]:
        return idx + delta if idx is not None and idx >= first_affected else idx

    def _build_tree_indent(self, depth: int, parent: str, is_last: bool) -> str:
        if depth == 1:
            connector = TREE_LAST if is_last else TREE_BRANCH
            return f"   {connector} "
        else:
            return (
                "   "
                + f"{TREE_VERTICAL}  " * (depth - 1)
                + (f"{TREE_LAST} " if is_last else f"{TREE_BRANCH} ")
            )

    def _render_nested_tool_line_for_state(self, state: NestedToolState) -> None:
        if state.line_number >= len(self.log.lines):
            return

        elapsed = round(time.monotonic() - state.timer_start)

        formatted = Text()
        indent = self._build_tree_indent(state.depth, state.parent, is_last=False)
        formatted.append(indent)
        color = GREEN_GRADIENT[state.color_index]
        formatted.append(f"{self._nested_spinner_char} ", style=color)
        formatted.append_text(state.tool_text.copy())
        formatted.append(f" ({elapsed}s)", style=GREY)

        strip = text_to_strip(formatted)
        self.log.lines[state.line_number] = strip
        self.log.refresh_line(state.line_number)

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
        color = GREEN_GRADIENT[self._nested_color_index]
        formatted.append(f"{self._nested_spinner_char} ", style=color)
        formatted.append_text(self._nested_tool_text.copy())
        formatted.append(f" ({elapsed}s)", style=GREY)

        strip = text_to_strip(formatted)
        self.log.lines[self._nested_tool_line] = strip
        self.log.refresh_line(self._nested_tool_line)

    # Result rendering methods

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
