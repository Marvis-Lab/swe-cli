from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

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
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager
from swecli.ui_textual.widgets.conversation.renderers.utils import (
    TREE_BRANCH,
    TREE_LAST,
    TREE_VERTICAL,
    TREE_CONTINUATION,
    text_to_strip,
)

@dataclass
class AgentInfo:
    """Info for a single parallel agent tracked by tool_call_id."""

    agent_type: str
    description: str
    tool_call_id: str
    line_number: int = 0  # Line for agent row
    status_line: int = 0  # Line for status/current tool
    tool_count: int = 0  # Total tool call count
    current_tool: str = "Initializing...."
    status: str = "running"  # running, completed, failed
    is_last: bool = False  # For tree connector rendering


@dataclass
class ParallelAgentGroup:
    """Tracks a group of parallel agents for collapsed display."""

    agents: Dict[str, AgentInfo] = field(default_factory=dict)  # key = tool_call_id
    header_line: int = 0
    expanded: bool = False
    start_time: float = field(default_factory=time.monotonic)
    completed: bool = False


class ParallelAgentRenderer:
    """Handles rendering of parallel agent execution groups."""

    def __init__(self, log: RichLogInterface, spacing_manager: SpacingManager):
        self.log = log
        self.spacing = spacing_manager

        # State
        self.group: Optional[ParallelAgentGroup] = None
        self.agent_spinner_states: Dict[str, int] = {}  # tool_call_id -> spinner_index
        self.header_spinner_index: int = 0

        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    @property
    def is_active(self) -> bool:
        """Check if there's an active parallel agent group."""
        return self.group is not None and not self.group.completed

    @property
    def is_expanded(self) -> bool:
        """Check if parallel group is expanded."""
        return self.group.expanded if self.group else False

    def on_start(self, agent_infos: List[dict], expanded_default: bool = False) -> None:
        """Called when parallel agents start executing."""
        self.spacing.before_parallel_agents()

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
            agent_row = Text()
            agent_row.append("   ⏺ ", style=GREEN_BRIGHT)  # Gradient bullet for agent rows
            agent_row.append(description)
            agent_row.append(" · 0 tools", style=GREY)
            self.log.write(agent_row, scroll_end=True, animate=False, wrappable=False)
            agent_line = len(self.log.lines) - 1

            # Status row: "      ⎿  Initializing...."
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

        self.group = ParallelAgentGroup(
            agents=agents,
            header_line=header_line,
            expanded=expanded_default,
            start_time=time.monotonic(),
        )

        # Reset animation indices
        self.header_spinner_index = 0
        self.agent_spinner_states.clear()

    def on_complete(self, tool_call_id: str, success: bool) -> None:
        """Called when a parallel agent completes."""
        if self.group is None:
            return

        agent = self.group.agents.get(tool_call_id)
        if agent is not None:
            # Update status
            agent.status = "completed" if success else "failed"

            # Update agent row with final status
            self._update_agent_row_completed(agent, success)

            # Update status line to show completion
            self._update_status_line_completed(agent, success)

            # Update header
            self._update_parallel_header()

    def on_all_done(self) -> None:
        """Called when all parallel agents have completed."""
        if self.group is None:
            return

        # Mark all agents as completed (in case some weren't explicitly marked)
        for agent in self.group.agents.values():
            if agent.status == "running":
                agent.status = "completed"
                self._update_agent_row_completed(agent, success=True)
                self._update_status_line_completed(agent, success=True)

        self.group.completed = True
        self._update_parallel_header()

        # Add blank line for spacing before next content
        self.spacing.after_parallel_agents()

        # Clear parallel group
        self.group = None

    def toggle_expansion(self) -> bool:
        """Toggle the expand/collapse state of parallel agent display."""
        if self.group:
            self.group.expanded = not self.group.expanded
            return self.group.expanded
        return False

    def animate(self) -> None:
        """Animate spinners and gradients."""
        if self.group is None:
            return

        # Animate header with rotating spinner
        if any(a.status == "running" for a in self.group.agents.values()):
            self.header_spinner_index += 1
            self._update_parallel_header()

        # Animate agent rows with gradient bullets
        for tool_call_id, agent in self.group.agents.items():
            if agent.status == "running":
                # Update gradient color index
                idx = self.agent_spinner_states.get(tool_call_id, 0)
                idx = (idx + 1) % len(GREEN_GRADIENT)
                self.agent_spinner_states[tool_call_id] = idx

                # Update agent row with gradient animation
                self._update_agent_row_gradient(agent, idx)

    def update_agent_tool(self, tool_call_id: str, tool_name: str) -> None:
        """Update agent's current tool display."""
        if self.group is None:
            return

        agent = self.group.agents.get(tool_call_id)
        if agent is not None:
            agent.tool_count += 1
            agent.current_tool = tool_name
            self._update_agent_row(agent)
            self._update_status_line(agent)

    def write_summaries(self) -> None:
        """Write summary lines for each agent."""
        if self.group is None:
            return

        agents = list(self.group.agents.items())
        for i, (name, stats) in enumerate(agents):
            is_last = i == len(agents) - 1
            connector = TREE_LAST if is_last else TREE_BRANCH

            text = Text()
            text.append(f"   {connector} ", style=GREY)
            text.append(f"{name}", style=PRIMARY)
            text.append(f" · {stats.tool_count} tool uses", style=GREY)

            if stats.current_tool:
                text.append("\n")
                continuation = "      " if is_last else f"   {TREE_VERTICAL}  "
                text.append(f"{continuation}{TREE_CONTINUATION}  ", style=GREY)
                text.append(stats.current_tool, style=SUBTLE)

            self.log.write(text, scroll_end=True, animate=False, wrappable=False)

    # --- Internal rendering methods ---

    def _render_parallel_header(self) -> Text:
        if self.group is None:
            return Text("")

        group = self.group
        total_agents = len(group.agents)
        total_tools = sum(a.tool_count for a in group.agents.values())
        all_completed = all(a.status in ("completed", "failed") for a in group.agents.values())
        any_failed = any(a.status == "failed" for a in group.agents.values())

        type_counts: Dict[str, int] = {}
        for agent in group.agents.values():
            type_counts[agent.agent_type] = type_counts.get(agent.agent_type, 0) + 1

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
            spinner_char = self._spinner_chars[
                self.header_spinner_index % len(self._spinner_chars)
            ]
            text.append(f"{spinner_char} ", style=CYAN)
            text.append(f"Running {agent_desc} {agent_word}… ")

        return text

    def _update_parallel_header(self) -> None:
        if self.group is None:
            return

        header_text = self._render_parallel_header()
        strip = text_to_strip(header_text)

        if self.group.header_line < len(self.log.lines):
            self.log.lines[self.group.header_line] = strip
            self.log.refresh_line(self.group.header_line)

    def _update_agent_row(self, agent: AgentInfo) -> None:
        if agent.line_number >= len(self.log.lines):
            return

        unique_count = agent.tool_count
        use_spinner = agent.status == "running"

        if use_spinner:
            idx = self.agent_spinner_states.get(agent.tool_call_id, 0)
            color_idx = idx % len(GREEN_GRADIENT)
            color = GREEN_GRADIENT[color_idx]
            row = Text()
            row.append("   ⏺ ", style=color)
            row.append(agent.description)
            row.append(f" · {unique_count} tool" + ("s" if unique_count != 1 else ""), style=GREY)
        else:
            status_char = "✓" if agent.status == "completed" else "✗"
            status_style = SUCCESS if agent.status == "completed" else ERROR
            row = Text()
            row.append(f"   {status_char} ", style=status_style)
            row.append(agent.description)
            row.append(f" · {unique_count} tool" + ("s" if unique_count != 1 else ""), style=GREY)

        strip = text_to_strip(row)
        self.log.lines[agent.line_number] = strip
        self.log.refresh_line(agent.line_number)

    def _update_status_line(self, agent: AgentInfo) -> None:
        if agent.status_line >= len(self.log.lines):
            return

        status = Text()
        status.append("      ⎿  ", style=GREY)
        status.append(agent.current_tool, style=SUBTLE)

        strip = text_to_strip(status)
        self.log.lines[agent.status_line] = strip
        self.log.refresh_line(agent.status_line)

    def _update_agent_row_gradient(self, agent: AgentInfo, color_idx: int) -> None:
        if agent.line_number >= len(self.log.lines):
            return

        unique_count = agent.tool_count
        color = GREEN_GRADIENT[color_idx % len(GREEN_GRADIENT)]
        row = Text()
        row.append("   ⏺ ", style=color)
        row.append(agent.description)
        row.append(f" · {unique_count} tool" + ("s" if unique_count != 1 else ""), style=GREY)

        strip = text_to_strip(row)
        self.log.lines[agent.line_number] = strip
        self.log.refresh_line(agent.line_number)

    def _update_agent_row_completed(self, agent: AgentInfo, success: bool) -> None:
        if agent.line_number >= len(self.log.lines):
            return

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
        if agent.status_line >= len(self.log.lines):
            return

        status_text = "Done" if success else "Failed"

        status = Text()
        status.append("      ⎿  ", style=GREY)
        status.append(status_text, style=SUBTLE if success else ERROR)

        strip = text_to_strip(status)
        self.log.lines[agent.status_line] = strip
        self.log.refresh_line(agent.status_line)

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        """Adjust line indices after resize/insertion."""
        if self.group is not None:
            if self.group.header_line >= first_affected:
                self.group.header_line += delta
            for agent in self.group.agents.values():
                if agent.line_number >= first_affected:
                    agent.line_number += delta
                if agent.status_line >= first_affected:
                    agent.status_line += delta
