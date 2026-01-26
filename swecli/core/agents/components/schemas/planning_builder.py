"""Planning tool schema builder for PLAN mode agents.

This module contains the PlanningToolSchemaBuilder which provides read-only
tools for codebase exploration in PLAN mode.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Union

from .definitions import _BUILTIN_TOOL_SCHEMAS


# Read-only tools allowed in PLAN mode for codebase exploration
PLANNING_TOOLS = {
    "read_file",
    "list_files",
    "search",  # Unified: type="text" (ripgrep) or "ast" (ast-grep)
    "fetch_url",
    "web_search",  # Web search is read-only
    "list_processes",
    "get_process_output",
    "read_pdf",  # PDF extraction is read-only
    # Symbol tools (read-only)
    "find_symbol",
    "find_referencing_symbols",
    # MCP tool discovery (read-only)
    "search_tools",
    # Skills (read-only - just loads knowledge into context)
    "invoke_skill",
    # Subagent spawning (subagents handle their own restrictions)
    "spawn_subagent",
    # User interaction (allows asking clarifying questions)
    "ask_user",
    # Task completion (always allowed - agents must signal completion)
    "task_complete",
}


class PlanningToolSchemaBuilder:
    """Assemble read-only tool schemas for PLAN mode agents.

    Planning agents can explore the codebase but cannot make changes.
    Includes spawn_subagent for asking user questions and other subagent tasks.
    """

    def __init__(self, tool_registry: Union[Any, None] = None) -> None:
        self._tool_registry = tool_registry

    def build(self) -> list[dict[str, Any]]:
        """Return read-only tool schemas including spawn_subagent for planning mode."""
        schemas = [
            deepcopy(schema)
            for schema in _BUILTIN_TOOL_SCHEMAS
            if schema["function"]["name"] in PLANNING_TOOLS
        ]

        # Add spawn_subagent schema (for ask-user and other subagents)
        task_schema = self._build_task_schema()
        if task_schema:
            schemas.append(task_schema)

        return schemas

    def _build_task_schema(self) -> dict[str, Any] | None:
        """Build task tool schema with available subagent types."""
        if not self._tool_registry:
            return None

        subagent_manager = getattr(self._tool_registry, "_subagent_manager", None)
        if not subagent_manager:
            return None

        from swecli.core.agents.subagents.task_tool import create_task_tool_schema

        return create_task_tool_schema(subagent_manager)
