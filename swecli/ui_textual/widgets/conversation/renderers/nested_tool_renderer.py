from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

from rich.text import Text
from textual.strip import Strip

from swecli.ui_textual.style_tokens import (
    ERROR,
    GREEN_GRADIENT,
    GREY,
    SUBTLE,
    SUCCESS,
)
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager
from swecli.ui_textual.widgets.conversation.renderers.models import NestedToolState
from swecli.ui_textual.widgets.conversation.renderers.utils import (
    TREE_BRANCH,
    TREE_LAST,
    TREE_VERTICAL,
    text_to_strip,
)


class NestedToolRenderer:
    """Handles rendering of nested tool calls."""

    def __init__(self, log: RichLogInterface, spacing_manager: SpacingManager):
        self.log = log
        self._spacing = spacing_manager

        self._nested_spinner_char = "⏺"
        # Multi-tool tracking: (parent, tool_id) -> NestedToolState
        self.tools: Dict[Tuple[str, str], NestedToolState] = {}

        # Legacy single-tool state (for backwards compatibility)
        self.legacy_line: Optional[int] = None
        self.legacy_text: Optional[Text] = None
        self.legacy_depth: int = 1
        self.legacy_color_index = 0
        self.legacy_timer_start: Optional[float] = None

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        """Adjust line indices when log is modified above."""
        self.legacy_line = self._adj(self.legacy_line, delta, first_affected)

        for state in self.tools.values():
            if state.line_number >= first_affected:
                state.line_number += delta

    def _adj(self, idx: Optional[int], delta: int, first_affected: int) -> Optional[int]:
        return idx + delta if idx is not None and idx >= first_affected else idx

    def has_active_tools(self) -> bool:
        """Check if there are any active nested tools."""
        return bool(self.tools) or (self.legacy_line is not None)

    def add_tool(
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
            tool_id = f"{parent}_{len(self.tools)}_{time.monotonic()}"

        key = (parent, tool_id)
        self.tools[key] = NestedToolState(
            line_number=len(self.log.lines) - 1,
            tool_text=tool_text.copy(),
            depth=depth,
            timer_start=time.monotonic(),
            color_index=0,
            parent=parent,
            tool_id=tool_id,
        )

        # Maintain legacy state
        self.legacy_line = len(self.log.lines) - 1
        self.legacy_text = tool_text.copy()
        self.legacy_depth = depth
        self.legacy_color_index = 0
        self.legacy_timer_start = time.monotonic()

    def complete_tool(
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
            state = self.tools.pop(key, None)

        if state is None:
            # Fallback: find most recent for parent
            for key in list(self.tools.keys()):
                if key[0] == parent:
                    state = self.tools.pop(key)
                    break

        # Legacy fallback
        if state is None:
            if self.legacy_line is None or self.legacy_text is None:
                return
            state = NestedToolState(
                line_number=self.legacy_line,
                tool_text=self.legacy_text,
                depth=self.legacy_depth,
                timer_start=self.legacy_timer_start or time.monotonic(),
                parent=parent,
            )
            # Clear legacy state
            self.legacy_line = None
            self.legacy_text = None
            self.legacy_timer_start = None

        # If the completed tool is the one tracked by legacy, clear legacy
        if self.legacy_line == state.line_number:
            self.legacy_line = None
            self.legacy_text = None
            self.legacy_timer_start = None

        # Build completed tool display
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

    def animate(self) -> None:
        """Animate active nested tools."""
        # Animate multi-tool tracking
        for state in self.tools.values():
            state.color_index = (state.color_index + 1) % len(GREEN_GRADIENT)
            self._render_state(state)

        # Animate legacy
        if self.legacy_line is not None and self.legacy_text is not None:
            self.legacy_color_index = (self.legacy_color_index + 1) % len(GREEN_GRADIENT)
            self._render_legacy()

    def _render_state(self, state: NestedToolState) -> None:
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

    def _render_legacy(self) -> None:
        if self.legacy_line is None or self.legacy_text is None:
            return
        if self.legacy_line >= len(self.log.lines):
            return

        elapsed = 0
        if self.legacy_timer_start:
            elapsed = round(time.monotonic() - self.legacy_timer_start)

        formatted = Text()
        indent = "  " * self.legacy_depth
        formatted.append(indent)
        color = GREEN_GRADIENT[self.legacy_color_index]
        formatted.append(f"{self._nested_spinner_char} ", style=color)
        formatted.append_text(self.legacy_text.copy())
        formatted.append(f" ({elapsed}s)", style=GREY)

        strip = text_to_strip(formatted)
        self.log.lines[self.legacy_line] = strip
        self.log.refresh_line(self.legacy_line)

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
