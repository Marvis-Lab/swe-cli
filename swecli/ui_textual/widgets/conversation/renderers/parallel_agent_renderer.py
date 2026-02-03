from typing import Dict, List, Optional
import time
from rich.text import Text
from textual.strip import Strip

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
from swecli.ui_textual.widgets.conversation.renderers.models import AgentInfo, ParallelAgentGroup
from swecli.ui_textual.widgets.conversation.renderers.utils import (
    TREE_BRANCH,
    TREE_CONTINUATION,
    TREE_LAST,
    TREE_VERTICAL,
    text_to_strip,
)
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager


class ParallelAgentRenderer:
    def __init__(self, log: RichLogInterface, spacing_manager: SpacingManager):
        self.log = log
        self._spacing = spacing_manager
        self._parallel_group: Optional[ParallelAgentGroup] = None
        self._parallel_expanded: bool = False
        self._agent_spinner_states: Dict[str, int] = {}
        self._header_spinner_index = 0
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    @property
    def parallel_group(self) -> Optional[ParallelAgentGroup]:
        return self._parallel_group

    @property
    def parallel_expanded(self) -> bool:
        return self._parallel_expanded

    def on_parallel_agents_start(self, agent_infos: List[dict]) -> None:
        """Called when parallel agents start executing.

        Creates a parallel group and renders header + individual agent lines with status.

        Args:
            agent_infos: List of agent info dicts with keys:
                - agent_type: Type of agent (e.g., "Explore")
                - description: Short description of agent's task
                - tool_call_id: Unique ID for tracking this agent
        """
        self._spacing.before_parallel_agents()

        # Write header line - updated in-place with spinner, don't re-wrap
        header = Text()
        header.append("⠋ ", style=CYAN)  # Rotating spinner for header
        header.append(f"Running {len(agent_infos)} agents… ")
        self.log.write(header, scroll_end=True, animate=False, wrappable=False)
        header_line = len(self.log.lines) - 1

        # Create agents dict keyed by tool_call_id
        agents: Dict[str, AgentInfo] = {}
        for i, info in enumerate(agent_infos):
            is_last = i == len(agent_infos) - 1
            tool_call_id = info.get("tool_call_id", f"agent_{i}")
            description = info.get("description") or info.get("agent_type", "Agent")
            agent_type = info.get("agent_type", "Agent")

            # Agent row: "   ⏺ Description · 0 tools" (gradient flashing bullet)
            # Updated in-place with spinner animation, don't re-wrap
            agent_row = Text()
            agent_row.append("   ⏺ ", style=GREEN_BRIGHT)  # Gradient bullet for agent rows
            agent_row.append(description)
            agent_row.append(" · 0 tools", style=GREY)
            self.log.write(agent_row, scroll_end=True, animate=False, wrappable=False)
            agent_line = len(self.log.lines) - 1

            # Status row: "      ⎿  Initializing...." (no tree connector for agent row)
            # Updated in-place, don't re-wrap
            status_row = Text()
            status_row.append("      ⎿  ", style=GREY)
            status_row.append("Initializing....", style=SUBTLE)
            self.log.write(status_row, scroll_end=True, animate=False, wrappable=False)
            status_line_num = len(self.log.lines) - 1

            agents[tool_call_id] = AgentInfo(
                agent_type=agent_type,
                description=description,
                tool_call_id=tool_call_id,
                line_number=agent_line,
                status_line=status_line_num,
                is_last=is_last,
            )

        self._parallel_group = ParallelAgentGroup(
            agents=agents,
            header_line=header_line,
            expanded=self._parallel_expanded,
            start_time=time.monotonic(),
        )

        # Reset animation indices for parallel agents
        self._header_spinner_index = 0
        self._agent_spinner_states.clear()

    def _render_parallel_header(self) -> Text:
        """Render the parallel agents header line.

        Returns:
            Text object for the header line
        """
        if self._parallel_group is None:
            return Text("")

        group = self._parallel_group
        total_agents = len(group.agents)
        total_tools = sum(a.tool_count for a in group.agents.values())
        all_completed = all(a.status in ("completed", "failed") for a in group.agents.values())
        any_failed = any(a.status == "failed" for a in group.agents.values())

        # Count agents by type for description
        type_counts: Dict[str, int] = {}
        for agent in group.agents.values():
            type_counts[agent.agent_type] = type_counts.get(agent.agent_type, 0) + 1

        # Build agent type description (e.g., "2 Explore agents" or "1 Explore + 1 Bash agents")
        type_descriptions = []
        for agent_type, count in type_counts.items():
            type_descriptions.append(f"{count} {agent_type}")
        agent_desc = (
            " + ".join(type_descriptions)
            if len(type_descriptions) > 1
            else type_descriptions[0] if type_descriptions else "0"
        )
        agent_word = "agent" if total_agents == 1 else "agents"

        text = Text()

        if all_completed:
            if any_failed:
                text.append("⏺ ", style=ERROR)
            else:
                text.append("⏺ ", style=SUCCESS)
            elapsed = round(time.monotonic() - group.start_time)
            text.append(f"Completed {agent_desc} {agent_word} ")
            text.append(f"({total_tools} tools · {elapsed}s)", style=GREY)
        else:
            # Use rotating spinner character from _header_spinner_index
            spinner_char = self._spinner_chars[
                self._header_spinner_index % len(self._spinner_chars)
            ]
            text.append(f"{spinner_char} ", style=CYAN)
            text.append(f"Running {agent_desc} {agent_word}… ")

        return text

    def update_parallel_header(self) -> None:
        """Update the parallel header line in-place."""
        if self._parallel_group is None:
            return

        header_text = self._render_parallel_header()
        strip = text_to_strip(header_text)

        if self._parallel_group.header_line < len(self.log.lines):
            self.log.lines[self._parallel_group.header_line] = strip
            self.log.refresh_line(self._parallel_group.header_line)

    def update_agent_row(self, agent: AgentInfo) -> None:
        """Update an agent's row line to show tool count (with gradient bullet if running).

        Args:
            agent: AgentInfo for the agent to update
        """
        if agent.line_number >= len(self.log.lines):
            return

        # Build agent row: "   ⏺ Description · N tools" (gradient bullet if running, checkmark if complete)
        unique_count = agent.tool_count
        use_spinner = agent.status == "running"

        if use_spinner:
            # Use gradient color for ⏺ bullet (animate through green gradient)
            idx = self._agent_spinner_states.get(agent.tool_call_id, 0)
            color_idx = idx % len(GREEN_GRADIENT)
            color = GREEN_GRADIENT[color_idx]
            row = Text()
            row.append("   ⏺ ", style=color)  # Gradient flashing bullet
            row.append(agent.description)
            row.append(f" · {unique_count} tool" + ("s" if unique_count != 1 else ""), style=GREY)
        else:
            # Use checkmark/X for completed agents
            status_char = "✓" if agent.status == "completed" else "✗"
            status_style = SUCCESS if agent.status == "completed" else ERROR
            row = Text()
            row.append(f"   {status_char} ", style=status_style)
            row.append(agent.description)
            row.append(f" · {unique_count} tool" + ("s" if unique_count != 1 else ""), style=GREY)

        strip = text_to_strip(row)
        self.log.lines[agent.line_number] = strip
        self.log.refresh_line(agent.line_number)

    def update_status_line(self, agent: AgentInfo) -> None:
        """Update an agent's status line with current tool.

        Args:
            agent: AgentInfo for the agent to update
        """
        if agent.status_line >= len(self.log.lines):
            return

        # Build status row: "      ⎿  Current tool name" (no tree connector)
        status = Text()
        status.append("      ⎿  ", style=GREY)
        status.append(agent.current_tool, style=SUBTLE)

        strip = text_to_strip(status)
        self.log.lines[agent.status_line] = strip
        self.log.refresh_line(agent.status_line)

    def _update_agent_row_gradient(self, agent: AgentInfo, color_idx: int) -> None:
        """Update agent row with animated gradient bullet.

        Args:
            agent: AgentInfo for the agent to update
            color_idx: Current color index for gradient animation
        """
        if agent.line_number >= len(self.log.lines):
            return

        # Build agent row: "   ⏺ Description · N tools" with gradient color
        unique_count = agent.tool_count
        color = GREEN_GRADIENT[color_idx % len(GREEN_GRADIENT)]
        row = Text()
        row.append("   ⏺ ", style=color)  # Gradient flashing bullet
        row.append(agent.description)
        row.append(f" · {unique_count} tool" + ("s" if unique_count != 1 else ""), style=GREY)

        strip = text_to_strip(row)
        self.log.lines[agent.line_number] = strip
        self.log.refresh_line(agent.line_number)

    def on_parallel_agent_complete(self, tool_call_id: str, success: bool) -> None:
        """Called when a parallel agent completes.

        Args:
            tool_call_id: Unique tool call ID of the agent that completed
            success: Whether the agent succeeded
        """
        if self._parallel_group is None:
            return

        agent = self._parallel_group.agents.get(tool_call_id)
        if agent is not None:
            # Update status
            agent.status = "completed" if success else "failed"

            # Update agent row with final status
            self._update_agent_row_completed(agent, success)

            # Update status line to show completion
            self._update_status_line_completed(agent, success)

            # Update header
            self.update_parallel_header()

    def _update_agent_row_completed(self, agent: AgentInfo, success: bool) -> None:
        """Update an agent's row line to show completion status.

        Args:
            agent: AgentInfo for the agent to update
            success: Whether the agent succeeded
        """
        if agent.line_number >= len(self.log.lines):
            return

        # Build completed agent row: "   ✓ Description · N tools" (green checkmark)
        status_char = "✓" if success else "✗"
        status_style = SUCCESS if success else ERROR
        unique_count = agent.tool_count

        row = Text()
        row.append(f"   {status_char} ", style=status_style)
        row.append(agent.description)
        row.append(f" · {unique_count} tool" + ("s" if unique_count != 1 else ""), style=GREY)

        strip = text_to_strip(row)
        self.log.lines[agent.line_number] = strip
        self.log.refresh_line(agent.line_number)

    def _update_status_line_completed(self, agent: AgentInfo, success: bool) -> None:
        """Update an agent's status line to show completion.

        Args:
            agent: AgentInfo for the agent to update
            success: Whether the agent succeeded
        """
        if agent.status_line >= len(self.log.lines):
            return

        # Build completed status row: "      ⎿  Done" or "      ⎿  Failed" (no tree connector)
        status_text = "Done" if success else "Failed"

        status = Text()
        status.append("      ⎿  ", style=GREY)
        status.append(status_text, style=SUBTLE if success else ERROR)

        strip = text_to_strip(status)
        self.log.lines[agent.status_line] = strip
        self.log.refresh_line(agent.status_line)

    def on_parallel_agents_done(self) -> None:
        """Called when all parallel agents have completed."""
        if self._parallel_group is None:
            return

        # Mark all agents as completed (in case some weren't explicitly marked)
        for agent in self._parallel_group.agents.values():
            if agent.status == "running":
                agent.status = "completed"
                self._update_agent_row_completed(agent, success=True)
                self._update_status_line_completed(agent, success=True)

        self._parallel_group.completed = True
        self.update_parallel_header()

        # Add blank line for spacing before next content
        self._spacing.after_parallel_agents()

        # Clear parallel group
        self._parallel_group = None

    def toggle_parallel_expansion(self) -> bool:
        """Toggle the expand/collapse state of parallel agent display.

        Returns:
            New expansion state (True = expanded)
        """
        self._parallel_expanded = not self._parallel_expanded
        return self._parallel_expanded

    def has_active_parallel_group(self) -> bool:
        """Check if there's an active parallel agent group.

        Returns:
            True if a parallel group is currently active
        """
        return self._parallel_group is not None and not self._parallel_group.completed

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        """Adjust all tracked line indices by delta."""
        if self._parallel_group is not None:
            if self._parallel_group.header_line >= first_affected:
                self._parallel_group.header_line += delta
            for agent in self._parallel_group.agents.values():
                if agent.line_number >= first_affected:
                    agent.line_number += delta
                if agent.status_line >= first_affected:
                    agent.status_line += delta

    def animate(self) -> None:
        """Animate parallel agents."""
        if self._parallel_group is None:
            return

        # Animate header with rotating spinner
        if any(a.status == "running" for a in self._parallel_group.agents.values()):
            self._header_spinner_index += 1  # Increment spinner frame for animation
            self.update_parallel_header()

        # Animate agent rows with gradient bullets
        for tool_call_id, agent in self._parallel_group.agents.items():
            if agent.status == "running":
                # Update gradient color index
                idx = self._agent_spinner_states.get(tool_call_id, 0)
                idx = (idx + 1) % len(GREEN_GRADIENT)
                self._agent_spinner_states[tool_call_id] = idx

                # Update agent row with gradient animation
                self._update_agent_row_gradient(agent, idx)
