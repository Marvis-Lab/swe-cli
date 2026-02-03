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
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager


class SingleAgentRenderer:
    def __init__(self, log: RichLogInterface, spacing_manager: SpacingManager):
        self.log = log
        self._spacing = spacing_manager
        self._single_agent: Optional[SingleAgentInfo] = None
        self._header_spinner_index = 0
        self._bullet_gradient_index = 0
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    @property
    def single_agent(self) -> Optional[SingleAgentInfo]:
        return self._single_agent

    def on_single_agent_start(self, agent_type: str, description: str, tool_call_id: str) -> None:
        """Called when a single agent starts (non-parallel execution).

        This creates the same display structure as parallel agents but for a single agent.

        Args:
            agent_type: Type of agent (e.g., "Explore", "Code-Explorer")
            description: Task description
            tool_call_id: Unique ID for tracking
        """
        self._spacing.before_single_agent()

        # Header line: "⠋ Explore(description)" - Rotating spinner
        # Updated in-place with animation, don't re-wrap
        header = Text()
        header.append("⠋ ", style=CYAN)
        header.append(f"{agent_type}(", style=CYAN)
        header.append(description, style=PRIMARY)
        header.append(")", style=CYAN)
        self.log.write(header, scroll_end=True, animate=False, wrappable=False)
        header_line = len(self.log.lines) - 1

        # Status line: "   ⏺ 0 tools" - Gradient flashing bullet
        # Updated in-place with animation, don't re-wrap
        status_row = Text()
        status_row.append("   ⏺ ", style=GREEN_BRIGHT)  # Will be animated with gradient
        status_row.append("0 tools", style=GREY)
        self.log.write(status_row, scroll_end=True, animate=False, wrappable=False)
        status_line_num = len(self.log.lines) - 1

        # Current tool line: "      ⎿  Initializing..."
        # Updated in-place, don't re-wrap
        tool_row = Text()
        tool_row.append("      ⎿  ", style=GREY)
        tool_row.append("Initializing...", style=SUBTLE)
        self.log.write(tool_row, scroll_end=True, animate=False, wrappable=False)
        tool_line_num = len(self.log.lines) - 1

        self._single_agent = SingleAgentInfo(
            agent_type=agent_type,
            description=description,
            tool_call_id=tool_call_id,
            header_line=header_line,
            status_line=status_line_num,
            tool_line=tool_line_num,
        )

        # Reset animation indices
        self._header_spinner_index = 0
        self._bullet_gradient_index = 0

    def _update_header_spinner(self) -> None:
        """Update header line with rotating spinner (⠋⠙⠹...)."""
        if self._single_agent is None:
            return

        agent = self._single_agent
        if agent.header_line >= len(self.log.lines):
            return

        # Get next spinner frame
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
        """Update single agent's status line with tool count and gradient bullet."""
        if self._single_agent is None or self._single_agent.status_line >= len(self.log.lines):
            return

        agent = self._single_agent
        row = Text()
        # Use gradient color for ⏺ bullet (animate through green gradient)
        color_idx = self._bullet_gradient_index % len(GREEN_GRADIENT)
        color = GREEN_GRADIENT[color_idx]
        row.append("   ⏺ ", style=color)  # Gradient flashing bullet
        row.append(f"{agent.tool_count} tool" + ("s" if agent.tool_count != 1 else ""), style=GREY)

        strip = text_to_strip(row)
        self.log.lines[agent.status_line] = strip
        self.log.refresh_line(agent.status_line)

    def update_single_agent_tool_line(self) -> None:
        """Update single agent's current tool line."""
        if self._single_agent is None or self._single_agent.tool_line >= len(self.log.lines):
            return

        agent = self._single_agent
        row = Text()
        row.append("      ⎿  ", style=GREY)
        row.append(agent.current_tool, style=SUBTLE)

        strip = text_to_strip(row)
        self.log.lines[agent.tool_line] = strip
        self.log.refresh_line(agent.tool_line)

    def on_single_agent_complete(self, tool_call_id: str, success: bool = True) -> None:
        """Called when a single agent completes.

        Note: Keeps the same display style (⠋ header, ⏺ bullet). Just stops animation.

        Args:
            tool_call_id: Unique ID of the agent that completed
            success: Whether the agent succeeded
        """
        if self._single_agent is None:
            return

        # Verify tool_call_id matches (if provided)
        if tool_call_id and self._single_agent.tool_call_id != tool_call_id:
            return

        agent = self._single_agent
        agent.status = "completed" if success else "failed"

        # Update header from spinner to green bullet on completion
        header_row = Text()
        header_row.append("⏺ ", style=GREEN_BRIGHT if success else ERROR)
        header_row.append(f"{agent.agent_type}(", style=CYAN)
        header_row.append(agent.description, style=PRIMARY)
        header_row.append(")", style=CYAN)

        strip = text_to_strip(header_row)
        if agent.header_line < len(self.log.lines):
            self.log.lines[agent.header_line] = strip
            self.log.refresh_line(agent.header_line)

        # Update status line with ⏺ bullet
        status_row = Text()
        status_row.append("   ⏺ ", style=GREEN_BRIGHT)  # Keep bullet style
        status_row.append(
            f"{agent.tool_count} tool" + ("s" if agent.tool_count != 1 else ""), style=GREY
        )

        strip = text_to_strip(status_row)
        if agent.status_line < len(self.log.lines):
            self.log.lines[agent.status_line] = strip
            self.log.refresh_line(agent.status_line)

        # Update tool line to show "Done"
        tool_row = Text()
        tool_row.append("      ⎿  ", style=GREY)
        tool_row.append("Done" if success else "Failed", style=SUBTLE if success else ERROR)

        strip = text_to_strip(tool_row)
        if agent.tool_line < len(self.log.lines):
            self.log.lines[agent.tool_line] = strip
            self.log.refresh_line(agent.tool_line)

        # Add blank line for spacing before next content
        self._spacing.after_single_agent()

        self._single_agent = None

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        """Adjust all tracked line indices by delta."""
        if self._single_agent is not None:
            if self._single_agent.header_line >= first_affected:
                self._single_agent.header_line += delta
            if self._single_agent.status_line >= first_affected:
                self._single_agent.status_line += delta
            if self._single_agent.tool_line >= first_affected:
                self._single_agent.tool_line += delta

    def animate(self) -> None:
        """Animate single agent."""
        if self._single_agent is not None and self._single_agent.status == "running":
            # Update header with rotating spinner
            self._update_header_spinner()

            # Update status line with gradient bullet
            self._bullet_gradient_index = (self._bullet_gradient_index + 1) % len(GREEN_GRADIENT)
            self._update_single_agent_status_line()
