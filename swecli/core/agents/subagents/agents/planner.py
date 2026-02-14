"""Planner subagent for read-only codebase exploration and planning.

This subagent is specifically designed for PLAN mode operations,
providing read-only access to the codebase for analysis and planning.
"""

from swecli.core.agents.prompts.loader import load_prompt
from swecli.core.agents.subagents.specs import SubAgentSpec
from swecli.core.agents.components import PLANNING_TOOLS

PLANNER_SUBAGENT = SubAgentSpec(
    name="Planner",
    description=(
        "Read-only codebase exploration and planning agent. Analyzes code, "
        "understands patterns, identifies relevant files, and creates detailed "
        "implementation plans. Use this when you need to explore the codebase "
        "and plan changes without making modifications."
    ),
    system_prompt=load_prompt("subagents/subagent_planner_system_prompt"),
    tools=list(PLANNING_TOOLS),
    model=None,  # Use default model from config
)
