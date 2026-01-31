from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Dict, Tuple, Optional

from rich.text import Text
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager
from swecli.ui_textual.style_tokens import (
    GREY, GREEN_GRADIENT, SUCCESS, ERROR
)
from swecli.ui_textual.widgets.conversation.renderers.utils import (
    TREE_BRANCH, TREE_LAST, TREE_VERTICAL, text_to_strip
)

@dataclass
class NestedToolState:
    """State tracking for a single nested tool call."""
    line_number: int
    tool_text: Text
    depth: int
    timer_start: float
    color_index: int = 0
    parent: str = ""
    tool_id: str = ""

class NestedToolRenderer:
    def __init__(self, log: RichLogInterface, spacing: SpacingManager):
        self.log = log
        self.spacing = spacing

        self.nested_tools: Dict[Tuple[str, str], NestedToolState] = {}
        self._nested_spinner_char = "⏺"

        # Legacy single-tool state
        self.legacy_tool_line: int | None = None
        self.legacy_tool_text: Text | None = None
        self.legacy_tool_depth: int = 1
        self.legacy_color_index = 0
        self.legacy_timer_start: float | None = None

    @property
    def has_active_tools(self) -> bool:
        return bool(self.nested_tools) or (self.legacy_tool_line is not None)

    def add_tool(self, display: Text, depth: int, parent: str, tool_id: str = "", is_last: bool = False) -> None:
        self.spacing.before_nested_tool_call()

        formatted = Text()
        indent = self._build_tree_indent(depth, is_last)
        formatted.append(indent)
        formatted.append(f"{self._nested_spinner_char} ", style=GREEN_GRADIENT[0])
        formatted.append_text(display)
        formatted.append(" (0s)", style=GREY)

        self.log.write(formatted, scroll_end=True, animate=False, wrappable=False)

        if not tool_id:
            tool_id = f"{parent}_{len(self.nested_tools)}_{time.monotonic()}"

        key = (parent, tool_id)
        self.nested_tools[key] = NestedToolState(
            line_number=len(self.log.lines) - 1,
            tool_text=display.copy(),
            depth=depth,
            timer_start=time.monotonic(),
            color_index=0,
            parent=parent,
            tool_id=tool_id,
        )

    def complete_tool(self, tool_name: str, depth: int, parent: str, success: bool, tool_id: str = "") -> None:
        state: Optional[NestedToolState] = None

        if tool_id:
            key = (parent, tool_id)
            state = self.nested_tools.pop(key, None)

        if state is None:
            # Fallback
            for key in list(self.nested_tools.keys()):
                if key[0] == parent:
                    state = self.nested_tools.pop(key)
                    break

        if state is None:
            if self.legacy_tool_line is None or self.legacy_tool_text is None:
                return
            state = NestedToolState(
                line_number=self.legacy_tool_line,
                tool_text=self.legacy_tool_text,
                depth=self.legacy_tool_depth,
                timer_start=self.legacy_timer_start or time.monotonic(),
                parent=parent,
            )
            self.legacy_tool_line = None
            self.legacy_tool_text = None
            self.legacy_timer_start = None

        self._render_completed_tool(state, success)

    def _render_completed_tool(self, state: NestedToolState, success: bool) -> None:
        formatted = Text()
        # Note: mimicking original behavior of is_last=False
        indent = self._build_tree_indent(state.depth, is_last=False)
        formatted.append(indent)
        status_char = "✓" if success else "✗"
        status_color = SUCCESS if success else ERROR

        formatted.append(f"{status_char} ", style=status_color)
        formatted.append_text(state.tool_text)

        elapsed = round(time.monotonic() - state.timer_start)
        formatted.append(f" ({elapsed}s)", style=GREY)

        if state.line_number < len(self.log.lines):
            self.log.lines[state.line_number] = text_to_strip(formatted)
            self.log.refresh_line(state.line_number)

    def animate(self) -> None:
        if not self.has_active_tools:
            return

        for key, state in self.nested_tools.items():
            state.color_index = (state.color_index + 1) % len(GREEN_GRADIENT)
            self._render_line_for_state(state)

        if self.legacy_tool_line is not None and self.legacy_tool_text is not None:
            self.legacy_color_index = (self.legacy_color_index + 1) % len(GREEN_GRADIENT)
            self._render_legacy_line()

    def _render_line_for_state(self, state: NestedToolState) -> None:
        if state.line_number >= len(self.log.lines):
            return

        elapsed = round(time.monotonic() - state.timer_start)

        formatted = Text()
        indent = self._build_tree_indent(state.depth, is_last=False)
        formatted.append(indent)
        color = GREEN_GRADIENT[state.color_index]
        formatted.append(f"{self._nested_spinner_char} ", style=color)
        formatted.append_text(state.tool_text.copy())
        formatted.append(f" ({elapsed}s)", style=GREY)

        self.log.lines[state.line_number] = text_to_strip(formatted)
        self.log.refresh_line(state.line_number)

    def _render_legacy_line(self) -> None:
        if self.legacy_tool_line is None or self.legacy_tool_text is None:
            return
        if self.legacy_tool_line >= len(self.log.lines):
            return

        elapsed = 0
        if self.legacy_timer_start:
            elapsed = round(time.monotonic() - self.legacy_timer_start)

        formatted = Text()
        indent = "  " * self.legacy_tool_depth
        formatted.append(indent)
        color = GREEN_GRADIENT[self.legacy_color_index]
        formatted.append(f"{self._nested_spinner_char} ", style=color)
        formatted.append_text(self.legacy_tool_text.copy())
        formatted.append(f" ({elapsed}s)", style=GREY)

        self.log.lines[self.legacy_tool_line] = text_to_strip(formatted)
        self.log.refresh_line(self.legacy_tool_line)

    def _build_tree_indent(self, depth: int, is_last: bool) -> str:
        if depth == 1:
            connector = TREE_LAST if is_last else TREE_BRANCH
            return f"   {connector} "
        else:
            return (
                "   "
                + f"{TREE_VERTICAL}  " * (depth - 1)
                + (f"{TREE_LAST} " if is_last else f"{TREE_BRANCH} ")
            )

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        for state in self.nested_tools.values():
            if state.line_number >= first_affected:
                state.line_number += delta

        if self.legacy_tool_line is not None and self.legacy_tool_line >= first_affected:
            self.legacy_tool_line += delta
