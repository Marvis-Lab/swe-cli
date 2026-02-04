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
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager
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
    """Handles rendering of parallel agent groups."""

    def __init__(self, log: RichLogInterface, spacing_manager: SpacingManager):
        self.log = log
        self._spacing = spacing_manager
        self.group: Optional[ParallelAgentGroup] = None

        # Spinner state
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._header_spinner_index = 0
        self._agent_spinner_states: Dict[str, int] = {}  # tool_call_id -> spinner_index

    def adjust_indices(self, delta: int, first_affected: int) -> None:
        """Adjust line indices when log is modified above."""
        if self.group is not None:
            if self.group.header_line >= first_affected:
                self.group.header_line += delta
            for agent in self.group.agents.values():
                if agent.line_number >= first_affected:
                    agent.line_number += delta
                if agent.status_line >= first_affected:
                    agent.status_line += delta

    def has_active_group(self) -> bool:
        """Check if there's an active parallel agent group."""
        return self.group is not None and not self.group.completed

    def start(self, agent_infos: List[dict], expanded_default: bool = False) -> None:
        """Start parallel agents execution display."""
        self._spacing.before_parallel_agents()

        # Write header line
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

        self.group = ParallelAgentGroup(
            agents=agents,
            header_line=header_line,
            expanded=expanded_default,
            start_time=time.monotonic(),
        )

        # Reset animation indices
        self._header_spinner_index = 0
        self._agent_spinner_states.clear()

    def complete_agent(self, tool_call_id: str, success: bool) -> None:
        """Mark an agent as complete."""
        if self.group is None:
            return

        agent = self.group.agents.get(tool_call_id)
        if agent is not None:
            agent.status = "completed" if success else "failed"
            self._update_agent_row_completed(agent, success)
            self._update_status_line_completed(agent, success)
            self.update_header()

    def done(self) -> None:
        """Mark all agents as done."""
        if self.group is None:
            return

        for agent in self.group.agents.values():
            if agent.status == "running":
                agent.status = "completed"
                self._update_agent_row_completed(agent, success=True)
                self._update_status_line_completed(agent, success=True)

        self.group.completed = True
        self.update_header()
        self._spacing.after_parallel_agents()

        # We don't clear the group immediately if we want to keep displaying it,
        # but the original code did: self._parallel_group = None
        # However, if we clear it, we lose the state needed for resizing.
        # But the original code cleared it. Let's stick to original behavior,
        # but maybe return the group or keep it for history?
        # Original: self._parallel_group = None
        self.group = None

    def toggle_expansion(self) -> bool:
        """Toggle the expand/collapse state."""
        if self.group:
            self.group.expanded = not self.group.expanded
            return self.group.expanded
        # If group is None (completed), we can't toggle.
        # But wait, if it's completed, we might still want to toggle if we kept it.
        # The original code sets self._parallel_group = None on done.
        # So presumably we can't toggle after done?
        # Wait, if we clear it, we can't expand it to see the summaries or details.
        # This seems like a limitation of the original code or my understanding.
        # But I must replicate original behavior.
        return False

    def update_agent_tool(self, tool_call_id: str, tool_name: str) -> None:
        """Update agent status with new tool usage."""
        if self.group is None:
            return

        agent = self.group.agents.get(tool_call_id)
        if agent is not None:
            agent.tool_count += 1
            agent.current_tool = tool_name
            self._update_agent_row(agent)
            self._update_status_line(agent)

    def animate(self) -> None:
        """Perform one frame of animation."""
        if self.group is None:
            return

        # Animate header
        if any(a.status == "running" for a in self.group.agents.values()):
            self._header_spinner_index += 1
            self.update_header()

        # Animate agent rows
        for tool_call_id, agent in self.group.agents.items():
            if agent.status == "running":
                idx = self._agent_spinner_states.get(tool_call_id, 0)
                idx = (idx + 1) % len(GREEN_GRADIENT)
                self._agent_spinner_states[tool_call_id] = idx
                self._update_agent_row_gradient(agent, idx)

    def update_header(self) -> None:
        """Update the parallel header line in-place."""
        if self.group is None:
            return

        text = self._render_header_text()
        strip = text_to_strip(text)

        if self.group.header_line < len(self.log.lines):
            self.log.lines[self.group.header_line] = strip
            self.log.refresh_line(self.group.header_line)

    def _render_header_text(self) -> Text:
        if self.group is None:
            return Text("")

        total_agents = len(self.group.agents)
        total_tools = sum(a.tool_count for a in self.group.agents.values())
        all_completed = all(a.status in ("completed", "failed") for a in self.group.agents.values())
        any_failed = any(a.status == "failed" for a in self.group.agents.values())

        type_counts: Dict[str, int] = {}
        for agent in self.group.agents.values():
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
            elapsed = round(time.monotonic() - self.group.start_time)
            text.append(f"Completed {agent_desc} {agent_word} ")
            text.append(f"({total_tools} tools · {elapsed}s)", style=GREY)
        else:
            spinner_char = self._spinner_chars[
                self._header_spinner_index % len(self._spinner_chars)
            ]
            text.append(f"{spinner_char} ", style=CYAN)
            text.append(f"Running {agent_desc} {agent_word}… ")

        return text

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
