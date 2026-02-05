from __future__ import annotations

from typing import Optional

from rich.text import Text

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
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.renderers.models import SingleAgentInfo
from swecli.ui_textual.widgets.conversation.renderers.utils import text_to_strip
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager


class SingleAgentRenderer:
    """Renderer for single agent execution."""

    def __init__(self, log: RichLogInterface, spacing: SpacingManager):
        self.log = log
        self._spacing = spacing

        # State
        self.agent: Optional[SingleAgentInfo] = None

        # Animation
        self._header_spinner_index = 0
        self._bullet_gradient_index = 0
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def on_single_agent_start(
        self, agent_type: str, description: str, tool_call_id: str
    ) -> None:
        """Called when a single agent starts."""
        self._spacing.before_single_agent()

        # Header line
        header = Text()
        header.append("⠋ ", style=CYAN)
        header.append(f"{agent_type}(", style=CYAN)
        header.append(description, style=PRIMARY)
        header.append(")", style=CYAN)
        self.log.write(header, scroll_end=True, animate=False, wrappable=False)
        header_line = len(self.log.lines) - 1

        # Status line
        status_row = Text()
        status_row.append("   ⏺ ", style=GREEN_BRIGHT)
        status_row.append("0 tools", style=GREY)
        self.log.write(status_row, scroll_end=True, animate=False, wrappable=False)
        status_line_num = len(self.log.lines) - 1

        # Current tool line
        tool_row = Text()
        tool_row.append("      ⎿  ", style=GREY)
        tool_row.append("Initializing...", style=SUBTLE)
        self.log.write(tool_row, scroll_end=True, animate=False, wrappable=False)
        tool_line_num = len(self.log.lines) - 1

        self.agent = SingleAgentInfo(
            agent_type=agent_type,
            description=description,
            tool_call_id=tool_call_id,
            header_line=header_line,
            status_line=status_line_num,
            tool_line=tool_line_num,
        )

        self._header_spinner_index = 0
        self._bullet_gradient_index = 0

    def on_tool_call(self, tool_name: str) -> None:
        """Called when the active agent calls a tool."""
        if self.agent is None or self.agent.status != "running":
            return

        self.agent.tool_count += 1
        self.agent.current_tool = tool_name

        self._update_header_spinner()
        self._update_status_line()
        self._update_tool_line()

    def on_single_agent_complete(self, tool_call_id: str, success: bool = True) -> None:
        """Called when a single agent completes."""
        if self.agent is None:
            return

        if tool_call_id and self.agent.tool_call_id != tool_call_id:
            return

        self.agent.status = "completed" if success else "failed"

        # Update header
        header_row = Text()
        header_row.append("⏺ ", style=GREEN_BRIGHT if success else ERROR)
        header_row.append(f"{self.agent.agent_type}(", style=CYAN)
        header_row.append(self.agent.description, style=PRIMARY)
        header_row.append(")", style=CYAN)

        strip = text_to_strip(header_row)
        if self.agent.header_line < len(self.log.lines):
            self.log.lines[self.agent.header_line] = strip
            self.log.refresh_line(self.agent.header_line)

        # Update status line
        status_row = Text()
        status_row.append("   ⏺ ", style=GREEN_BRIGHT)
        status_row.append(
            f"{self.agent.tool_count} tool" + ("s" if self.agent.tool_count != 1 else ""), style=GREY
        )

        strip = text_to_strip(status_row)
        if self.agent.status_line < len(self.log.lines):
            self.log.lines[self.agent.status_line] = strip
            self.log.refresh_line(self.agent.status_line)

        # Update tool line
        tool_row = Text()
        tool_row.append("      ⎿  ", style=GREY)
        tool_row.append("Done" if success else "Failed", style=SUBTLE if success else ERROR)

        strip = text_to_strip(tool_row)
        if self.agent.tool_line < len(self.log.lines):
            self.log.lines[self.agent.tool_line] = strip
            self.log.refresh_line(self.agent.tool_line)

        self._spacing.after_single_agent()
        self.agent = None

    def animate(self) -> None:
        """Perform one frame of animation."""
        if self.agent is not None and self.agent.status == "running":
            self._update_header_spinner()
            self._bullet_gradient_index += 1
            self._update_status_line_animated()

    def has_active_agent(self) -> bool:
        return self.agent is not None and self.agent.status == "running"

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        """Adjust line indices after resize."""
        if self.agent is not None:
            if self.agent.header_line >= first_affected:
                self.agent.header_line += delta
            if self.agent.status_line >= first_affected:
                self.agent.status_line += delta
            if self.agent.tool_line >= first_affected:
                self.agent.tool_line += delta

    def _update_header_spinner(self) -> None:
        if self.agent is None or self.agent.header_line >= len(self.log.lines):
            return

        idx = self._header_spinner_index % len(self._spinner_chars)
        self._header_spinner_index += 1
        spinner_char = self._spinner_chars[idx]

        row = Text()
        row.append(f"{spinner_char} ", style=CYAN)
        row.append(f"{self.agent.agent_type}(", style=CYAN)
        row.append(self.agent.description, style=PRIMARY)
        row.append(")", style=CYAN)

        strip = text_to_strip(row)
        self.log.lines[self.agent.header_line] = strip
        self.log.refresh_line(self.agent.header_line)

    def _update_status_line(self) -> None:
        """Update status line (non-animated part)."""
        if self.agent is None or self.agent.status_line >= len(self.log.lines):
            return

        # We reuse the animated one but maybe just keep current color?
        # The original code called _update_single_agent_status_line which uses _bullet_gradient_index
        self._update_status_line_animated()

    def _update_status_line_animated(self) -> None:
        if self.agent is None or self.agent.status_line >= len(self.log.lines):
            return

        row = Text()
        color_idx = self._bullet_gradient_index % len(GREEN_GRADIENT)
        color = GREEN_GRADIENT[color_idx]
        row.append("   ⏺ ", style=color)
        row.append(f"{self.agent.tool_count} tool" + ("s" if self.agent.tool_count != 1 else ""), style=GREY)

        strip = text_to_strip(row)
        self.log.lines[self.agent.status_line] = strip
        self.log.refresh_line(self.agent.status_line)

    def _update_tool_line(self) -> None:
        if self.agent is None or self.agent.tool_line >= len(self.log.lines):
            return

        row = Text()
        row.append("      ⎿  ", style=GREY)
        row.append(self.agent.current_tool, style=SUBTLE)

        strip = text_to_strip(row)
        self.log.lines[self.agent.tool_line] = strip
        self.log.refresh_line(self.agent.tool_line)
