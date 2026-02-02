from __future__ import annotations

import time
from typing import Dict, List, Optional

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
from swecli.ui_textual.widgets.conversation.renderers.models import (
    AgentInfo,
    ParallelAgentGroup,
)
from swecli.ui_textual.widgets.conversation.renderers.utils import (
    TREE_BRANCH,
    TREE_CONTINUATION,
    TREE_LAST,
    TREE_VERTICAL,
    text_to_strip,
)


class ParallelAgentRenderer:
    """Renderer for parallel agent groups."""

    def __init__(self, log, spacing_manager):
        self.log = log
        self._spacing = spacing_manager
        self.parallel_group: Optional[ParallelAgentGroup] = None
        self.expanded: bool = False
        self._agent_spinner_states: Dict[str, int] = {}
        self._header_spinner_index = 0
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def has_active_group(self) -> bool:
        """Check if there is an active (running) parallel group."""
        return self.parallel_group is not None and not self.parallel_group.completed

    def has_running_agents(self) -> bool:
        """Check if any agents in the group are running."""
        if self.parallel_group is None:
            return False
        return any(a.status == "running" for a in self.parallel_group.agents.values())

    def start(self, agent_infos: List[dict]) -> None:
        """Called when parallel agents start executing."""
        self._spacing.before_parallel_agents()

        # Write header line
        header = Text()
        header.append("⠋ ", style=CYAN)
        header.append(f"Running {len(agent_infos)} agents… ")
        self.log.write(header, scroll_end=True, animate=False, wrappable=False)
        header_line = len(self.log.lines) - 1

        # Create agents dict
        agents: Dict[str, AgentInfo] = {}
        for i, info in enumerate(agent_infos):
            is_last = i == len(agent_infos) - 1
            tool_call_id = info.get("tool_call_id", f"agent_{i}")
            description = info.get("description") or info.get("agent_type", "Agent")
            agent_type = info.get("agent_type", "Agent")

            # Agent row
            agent_row = Text()
            agent_row.append("   ⏺ ", style=GREEN_BRIGHT)
            agent_row.append(description)
            agent_row.append(" · 0 tools", style=GREY)
            self.log.write(agent_row, scroll_end=True, animate=False, wrappable=False)
            agent_line = len(self.log.lines) - 1

            # Status row
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

        self.parallel_group = ParallelAgentGroup(
            agents=agents,
            header_line=header_line,
            expanded=self.expanded,
            start_time=time.monotonic(),
        )

        self._header_spinner_index = 0
        self._agent_spinner_states.clear()

    def update_tool_call(self, parent_id: str, tool_text: Text | str) -> bool:
        """Update stats and status line for a tool call.

        Returns:
            bool: True if the tool line should be rendered (expanded), False if collapsed.
        """
        if self.parallel_group is None:
            return True  # Should probably not happen if called correctly

        agent = self.parallel_group.agents.get(parent_id)
        if agent is None:
            return True  # Unknown agent, maybe render it?

        # Extract tool name
        plain_text = tool_text.plain if hasattr(tool_text, "plain") else str(tool_text)
        if ":" in plain_text:
            tool_name = plain_text.split(":")[0].strip()
        elif "(" in plain_text:
            tool_name = plain_text.split("(")[0].strip()
        else:
            tool_name = plain_text.split()[0] if plain_text.split() else "unknown"

        agent.tool_count += 1
        agent.current_tool = plain_text

        self._update_agent_row(agent)
        self._update_status_line(agent)

        return self.expanded

    def complete_agent(self, tool_call_id: str, success: bool) -> None:
        """Called when a parallel agent completes."""
        if self.parallel_group is None:
            return

        agent = self.parallel_group.agents.get(tool_call_id)
        if agent is not None:
            agent.status = "completed" if success else "failed"
            self._update_agent_row_completed(agent, success)
            self._update_status_line_completed(agent, success)
            self._update_parallel_header()

    def done(self) -> None:
        """Called when all parallel agents have completed."""
        if self.parallel_group is None:
            return

        for agent in self.parallel_group.agents.values():
            if agent.status == "running":
                agent.status = "completed"
                self._update_agent_row_completed(agent, success=True)
                self._update_status_line_completed(agent, success=True)

        self.parallel_group.completed = True
        self._update_parallel_header()
        self._spacing.after_parallel_agents()
        self.parallel_group = None

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        """Adjust line indices for resize events."""
        if self.parallel_group is not None:
            if self.parallel_group.header_line >= first_affected:
                self.parallel_group.header_line += delta
            for agent in self.parallel_group.agents.values():
                if agent.line_number >= first_affected:
                    agent.line_number += delta
                if agent.status_line >= first_affected:
                    agent.status_line += delta

    def toggle_expansion(self) -> bool:
        """Toggle the expand/collapse state."""
        self.expanded = not self.expanded
        if self.parallel_group:
            self.parallel_group.expanded = self.expanded
        return self.expanded

    def animate(self) -> None:
        """Animate spinners for running agents."""
        if self.parallel_group is None:
            return

        # Animate header
        if any(a.status == "running" for a in self.parallel_group.agents.values()):
            self._header_spinner_index += 1
            self._update_parallel_header()

        # Animate rows
        for tool_call_id, agent in self.parallel_group.agents.items():
            if agent.status == "running":
                idx = self._agent_spinner_states.get(tool_call_id, 0)
                idx = (idx + 1) % len(GREEN_GRADIENT)
                self._agent_spinner_states[tool_call_id] = idx
                self._update_agent_row_gradient(agent, idx)

    def write_summaries(self) -> None:
        """Write summary lines for each agent."""
        if self.parallel_group is None:
            return

        agents = list(self.parallel_group.agents.items())
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

    # --- Internal Helpers ---

    def _render_parallel_header(self) -> Text:
        if self.parallel_group is None:
            return Text("")

        group = self.parallel_group
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
                self._header_spinner_index % len(self._spinner_chars)
            ]
            text.append(f"{spinner_char} ", style=CYAN)
            text.append(f"Running {agent_desc} {agent_word}… ")

        return text

    def _update_parallel_header(self) -> None:
        if self.parallel_group is None:
            return

        header_text = self._render_parallel_header()
        strip = text_to_strip(header_text)

        if self.parallel_group.header_line < len(self.log.lines):
            self.log.lines[self.parallel_group.header_line] = strip
            self.log.refresh_line(self.parallel_group.header_line)

    def _update_agent_row(self, agent: AgentInfo) -> None:
        if agent.line_number >= len(self.log.lines):
            return

        unique_count = agent.tool_count
        use_spinner = agent.status == "running"

        if use_spinner:
            idx = self._agent_spinner_states.get(agent.tool_call_id, 0)
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
