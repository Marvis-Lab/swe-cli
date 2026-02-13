from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from rich.text import Text
from textual.strip import Strip
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager
from swecli.ui_textual.style_tokens import (
    CYAN, PRIMARY, GREEN_BRIGHT, GREY, SUBTLE, ERROR, GREEN_GRADIENT, SUCCESS
)
from swecli.ui_textual.widgets.conversation.renderers.utils import text_to_strip

@dataclass
class SingleAgentInfo:
    """Info for a single (non-parallel) agent execution."""
    agent_type: str
    description: str
    tool_call_id: str
    header_line: int = 0
    status_line: int = 0
    tool_line: int = 0
    tool_count: int = 0
    current_tool: str = "Initializing..."
    status: str = "running"

class SingleAgentRenderer:
    def __init__(self, log: RichLogInterface, spacing: SpacingManager):
        self.log = log
        self.spacing = spacing
        self.agent: Optional[SingleAgentInfo] = None
        self.header_spinner_index = 0
        self.bullet_gradient_index = 0
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    @property
    def is_active(self) -> bool:
        return self.agent is not None and self.agent.status == "running"

    def on_start(self, agent_type: str, description: str, tool_call_id: str) -> None:
        self.spacing.before_single_agent()

        header = Text()
        header.append("⠋ ", style=CYAN)
        header.append(f"{agent_type}(", style=CYAN)
        header.append(description, style=PRIMARY)
        header.append(")", style=CYAN)
        self.log.write(header, scroll_end=True, animate=False, wrappable=False)
        header_line = len(self.log.lines) - 1

        status_row = Text()
        status_row.append("   ⏺ ", style=GREEN_BRIGHT)
        status_row.append("0 tools", style=GREY)
        self.log.write(status_row, scroll_end=True, animate=False, wrappable=False)
        status_line = len(self.log.lines) - 1

        tool_row = Text()
        tool_row.append("      ⎿  ", style=GREY)
        tool_row.append("Initializing...", style=SUBTLE)
        self.log.write(tool_row, scroll_end=True, animate=False, wrappable=False)
        tool_line = len(self.log.lines) - 1

        self.agent = SingleAgentInfo(
            agent_type=agent_type,
            description=description,
            tool_call_id=tool_call_id,
            header_line=header_line,
            status_line=status_line,
            tool_line=tool_line,
        )
        self.header_spinner_index = 0
        self.bullet_gradient_index = 0

    def update_tool(self, tool_name: str) -> None:
        if not self.agent:
            return

        self.agent.tool_count += 1
        self.agent.current_tool = tool_name

        self.update_header()
        self.update_status(animate=False)
        self.update_tool_line()

    def update_header(self) -> None:
        if not self.agent or self.agent.header_line >= len(self.log.lines):
            return

        idx = self.header_spinner_index % len(self._spinner_chars)
        self.header_spinner_index += 1
        spinner_char = self._spinner_chars[idx]

        row = Text()
        row.append(f"{spinner_char} ", style=CYAN)
        row.append(f"{self.agent.agent_type}(", style=CYAN)
        row.append(self.agent.description, style=PRIMARY)
        row.append(")", style=CYAN)

        strip = text_to_strip(row)
        self.log.lines[self.agent.header_line] = strip
        self.log.refresh_line(self.agent.header_line)

    def update_status(self, animate: bool = False) -> None:
        if not self.agent or self.agent.status_line >= len(self.log.lines):
            return

        if animate:
            self.bullet_gradient_index += 1

        color_idx = self.bullet_gradient_index % len(GREEN_GRADIENT)
        color = GREEN_GRADIENT[color_idx]

        row = Text()
        row.append("   ⏺ ", style=color)
        row.append(f"{self.agent.tool_count} tool" + ("s" if self.agent.tool_count != 1 else ""), style=GREY)

        strip = text_to_strip(row)
        self.log.lines[self.agent.status_line] = strip
        self.log.refresh_line(self.agent.status_line)

    def update_tool_line(self) -> None:
        if not self.agent or self.agent.tool_line >= len(self.log.lines):
            return

        row = Text()
        row.append("      ⎿  ", style=GREY)
        row.append(self.agent.current_tool, style=SUBTLE)

        strip = text_to_strip(row)
        self.log.lines[self.agent.tool_line] = strip
        self.log.refresh_line(self.agent.tool_line)

    def on_complete(self, tool_call_id: str, success: bool = True) -> None:
        if not self.agent:
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

        if self.agent.header_line < len(self.log.lines):
            self.log.lines[self.agent.header_line] = text_to_strip(header_row)
            self.log.refresh_line(self.agent.header_line)

        # Update status line
        status_row = Text()
        status_row.append("   ⏺ ", style=GREEN_BRIGHT)
        status_row.append(
            f"{self.agent.tool_count} tool" + ("s" if self.agent.tool_count != 1 else ""), style=GREY
        )

        if self.agent.status_line < len(self.log.lines):
            self.log.lines[self.agent.status_line] = text_to_strip(status_row)
            self.log.refresh_line(self.agent.status_line)

        # Update tool line
        tool_row = Text()
        tool_row.append("      ⎿  ", style=GREY)
        tool_row.append("Done" if success else "Failed", style=SUBTLE if success else ERROR)

        if self.agent.tool_line < len(self.log.lines):
            self.log.lines[self.agent.tool_line] = text_to_strip(tool_row)
            self.log.refresh_line(self.agent.tool_line)

        self.spacing.after_single_agent()
        self.agent = None

    def animate(self) -> None:
        """Animate spinner and gradient."""
        if not self.is_active:
            return

        self.update_header()
        self.update_status(animate=True)

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        """Adjust line indices after resize/insertion."""
        if self.agent is not None:
            if self.agent.header_line >= first_affected:
                self.agent.header_line += delta
            if self.agent.status_line >= first_affected:
                self.agent.status_line += delta
            if self.agent.tool_line >= first_affected:
                self.agent.tool_line += delta
