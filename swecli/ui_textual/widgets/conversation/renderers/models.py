from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from rich.text import Text


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
class SingleAgentInfo:
    """Info for a single (non-parallel) agent execution."""

    agent_type: str
    description: str
    tool_call_id: str
    header_line: int = 0  # Line for header "⠋ Explore(description)"
    status_line: int = 0  # Line for "   ⏺ N tools" or "      ⎿  current_tool"
    tool_line: int = 0  # Line for "      ⎿  current_tool"
    tool_count: int = 0  # Total tool call count
    current_tool: str = "Initializing..."
    status: str = "running"


@dataclass
class ParallelAgentGroup:
    """Tracks a group of parallel agents for collapsed display."""

    agents: Dict[str, AgentInfo] = field(default_factory=dict)  # key = tool_call_id
    header_line: int = 0
    expanded: bool = False
    start_time: float = field(default_factory=time.monotonic)
    completed: bool = False


@dataclass
class AgentStats:
    """Stats tracking for a single agent type in a parallel group (legacy)."""

    tool_count: int = 0
    token_count: int = 0
    current_tool: str = ""
    status: str = "running"  # running, completed, failed
    agent_count: int = 1  # Number of agents of this type (for "Running 2 Explore agents")
    completed_count: int = 0  # Number of agents that have completed
