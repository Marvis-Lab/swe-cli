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
from swecli.ui_textual.widgets.conversation.renderers.models import SingleAgentInfo
from swecli.ui_textual.widgets.conversation.renderers.utils import text_to_strip


class SingleAgentRenderer:
    """Renderer for single (non-parallel) agent execution."""

    def __init__(self, log, spacing_manager):
        self.log = log
        self._spacing = spacing_manager
        self.single_agent: Optional[SingleAgentInfo] = None
        self._header_spinner_index = 0
        self._bullet_gradient_index = 0
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def has_active_agent(self) -> bool:
        """Check if there is an active (running) single agent."""
        return self.single_agent is not None and self.single_agent.status == "running"

    def start(self, agent_type: str, description: str, tool_call_id: str) -> None:
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

        self.single_agent = SingleAgentInfo(
            agent_type=agent_type,
            description=description,
            tool_call_id=tool_call_id,
            header_line=header_line,
            status_line=status_line_num,
            tool_line=tool_line_num,
        )

        self._header_spinner_index = 0
        self._bullet_gradient_index = 0

    def update_tool_call(self, tool_text: Text | str) -> bool:
        """Update single agent stats for a tool call.

        Returns:
            bool: Always False (single agent mode collapses nested tools by default)
        """
        if self.single_agent is None:
            return False

        # Extract tool name
        plain_text = tool_text.plain if hasattr(tool_text, "plain") else str(tool_text)
        if ":" in plain_text:
            tool_name = plain_text.split(":")[0].strip()
        elif "(" in plain_text:
            tool_name = plain_text.split("(")[0].strip()
        else:
            tool_name = plain_text.split()[0] if plain_text.split() else "unknown"

        self.single_agent.tool_count += 1
        self.single_agent.current_tool = plain_text

        self._update_header_spinner()
        self._update_single_agent_status_line()
        self._update_single_agent_tool_line()

        return False  # Don't render individual tools

    def complete(self, tool_call_id: str, success: bool = True) -> None:
        """Called when a single agent completes."""
        if self.single_agent is None:
            return

        if tool_call_id and self.single_agent.tool_call_id != tool_call_id:
            return

        agent = self.single_agent
        agent.status = "completed" if success else "failed"

        # Update header
        header_row = Text()
        header_row.append("⏺ ", style=GREEN_BRIGHT if success else ERROR)
        header_row.append(f"{agent.agent_type}(", style=CYAN)
        header_row.append(agent.description, style=PRIMARY)
        header_row.append(")", style=CYAN)

        strip = text_to_strip(header_row)
        if agent.header_line < len(self.log.lines):
            self.log.lines[agent.header_line] = strip
            self.log.refresh_line(agent.header_line)

        # Update status line
        status_row = Text()
        status_row.append("   ⏺ ", style=GREEN_BRIGHT)
        status_row.append(
            f"{agent.tool_count} tool" + ("s" if agent.tool_count != 1 else ""), style=GREY
        )

        strip = text_to_strip(status_row)
        if agent.status_line < len(self.log.lines):
            self.log.lines[agent.status_line] = strip
            self.log.refresh_line(agent.status_line)

        # Update tool line
        tool_row = Text()
        tool_row.append("      ⎿  ", style=GREY)
        tool_row.append("Done" if success else "Failed", style=SUBTLE if success else ERROR)

        strip = text_to_strip(tool_row)
        if agent.tool_line < len(self.log.lines):
            self.log.lines[agent.tool_line] = strip
            self.log.refresh_line(agent.tool_line)

        self._spacing.after_single_agent()
        self.single_agent = None

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        """Adjust line indices for resize events."""
        if self.single_agent is not None:
            if self.single_agent.header_line >= first_affected:
                self.single_agent.header_line += delta
            if self.single_agent.status_line >= first_affected:
                self.single_agent.status_line += delta
            if self.single_agent.tool_line >= first_affected:
                self.single_agent.tool_line += delta

    def animate(self) -> None:
        """Animate spinners for running single agent."""
        if self.single_agent is None or self.single_agent.status != "running":
            return

        self._update_header_spinner()
        self._bullet_gradient_index = (self._bullet_gradient_index + 1) % len(GREEN_GRADIENT)
        self._update_single_agent_status_line()

    # --- Internal Helpers ---

    def _update_header_spinner(self) -> None:
        if self.single_agent is None:
            return

        agent = self.single_agent
        if agent.header_line >= len(self.log.lines):
            return

        idx = self._header_spinner_index % len(self._spinner_chars)
        self._header_spinner_index += 1
        spinner_char = self._spinner_chars[idx]

        row = Text()
        row.append(f"{spinner_char} ", style=CYAN)
        row.append(f"{agent.agent_type}(", style=CYAN)
        row.append(agent.description, style=PRIMARY)
        row.append(")", style=CYAN)

        strip = text_to_strip(row)
        self.log.lines[agent.header_line] = strip
        self.log.refresh_line(agent.header_line)

    def _update_single_agent_status_line(self) -> None:
        if self.single_agent is None or self.single_agent.status_line >= len(self.log.lines):
            return

        agent = self.single_agent
        row = Text()
        color_idx = self._bullet_gradient_index % len(GREEN_GRADIENT)
        color = GREEN_GRADIENT[color_idx]
        row.append("   ⏺ ", style=color)
        row.append(f"{agent.tool_count} tool" + ("s" if agent.tool_count != 1 else ""), style=GREY)

        strip = text_to_strip(row)
        self.log.lines[agent.status_line] = strip
        self.log.refresh_line(agent.status_line)

    def _update_single_agent_tool_line(self) -> None:
        if self.single_agent is None or self.single_agent.tool_line >= len(self.log.lines):
            return

        agent = self.single_agent
        row = Text()
        row.append("      ⎿  ", style=GREY)
        row.append(agent.current_tool, style=SUBTLE)

        strip = text_to_strip(row)
        self.log.lines[agent.tool_line] = strip
        self.log.refresh_line(agent.tool_line)
