"""System prompt builders for SWE-CLI agents."""

from __future__ import annotations

import sys
from datetime import date
from typing import Any, TYPE_CHECKING

from swecli.core.agents.prompts import load_prompt

if TYPE_CHECKING:
    from swecli.core.skills import SkillLoader
    from swecli.core.agents.subagents.manager import SubAgentManager


class SystemPromptBuilder:
    """Constructs the NORMAL mode system prompt with optional MCP tooling.

    Uses a component-based architecture for assembling the system prompt:
    - Core identity (from main_system_prompt.txt)
    - Environment context (working directory, platform, date)
    - Agent index (available subagents for spawn_subagent tool)
    - Skills index (available skills for invoke_skill tool)
    - MCP section (connected servers)
    """

    def __init__(
        self,
        tool_registry: Any | None,
        working_dir: Any | None = None,
        skill_loader: "SkillLoader | None" = None,
        subagent_manager: "SubAgentManager | None" = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._working_dir = working_dir
        self._skill_loader = skill_loader
        self._subagent_manager = subagent_manager

    def build(self) -> str:
        """Build complete system prompt from components."""
        sections = [
            self._build_core_identity(),
            self._build_environment(),
            self._build_agent_index(),
            self._build_skills_index(),
            self._build_mcp_section() or self._build_mcp_config_section(),
        ]
        return "\n\n".join(filter(None, sections))

    def _build_core_identity(self) -> str:
        """Load and return core identity from main_system_prompt.txt.

        Handles the {available_agents} placeholder for backwards compatibility.
        """
        prompt = load_prompt("main_system_prompt")
        # Replace placeholder with actual agent list
        prompt = self._inject_available_agents(prompt)
        return prompt

    def _build_environment(self) -> str:
        """Build environment context section."""
        if not self._working_dir:
            return ""
        return f"""# Working Directory Context

You are currently working in the directory: `{self._working_dir}`

When processing file paths without explicit directories (like `app.py` or `README.md`), assume they are located in the current working directory unless the user provides a specific path. Use relative paths from the working directory for file operations."""

    def _build_agent_index(self) -> str:
        """Build available agents section from SubAgentManager.

        Uses the new build_task_tool_description() method if available.
        """
        # Try to get subagent_manager from multiple sources
        manager = self._subagent_manager
        if not manager and self._tool_registry:
            manager = getattr(self._tool_registry, "_subagent_manager", None)

        if not manager:
            return ""

        # Use the new method if available
        if hasattr(manager, "build_task_tool_description"):
            desc = manager.build_task_tool_description()
            return f"## Subagent System\n\n{desc}"

        return ""

    def _build_skills_index(self) -> str:
        """Build available skills section from SkillLoader."""
        # Try to get skill_loader from multiple sources
        loader = self._skill_loader
        if not loader and self._tool_registry:
            loader = getattr(self._tool_registry, "_skill_loader", None)

        if not loader:
            return ""

        return loader.build_skills_index()

    def _inject_available_agents(self, prompt: str) -> str:
        """Replace {available_agents} placeholder with actual subagent descriptions.

        This maintains backwards compatibility with the template placeholder.
        """
        if "{available_agents}" not in prompt:
            return prompt

        # Try to get subagent_manager
        manager = self._subagent_manager
        if not manager and self._tool_registry:
            manager = getattr(self._tool_registry, "_subagent_manager", None)

        if not manager:
            return prompt.replace("{available_agents}", "(No subagents available)")

        available_types = manager.get_available_types()
        if not available_types:
            return prompt.replace("{available_agents}", "(No subagents available)")

        # Build the available agents list
        descriptions = manager.get_descriptions()
        agent_lines = []
        for name in available_types:
            desc = descriptions.get(name, "No description")
            agent_lines.append(f"- **{name}**: {desc}")

        available_agents_str = "\n".join(agent_lines)
        return prompt.replace("{available_agents}", available_agents_str)

    def _build_mcp_section(self) -> str:
        """Render MCP section - shows connected servers, not individual tools.

        Individual tool schemas are NOT loaded by default for token efficiency.
        The agent must use search_tools() to discover and enable tools.
        """
        if not self._tool_registry or not getattr(self._tool_registry, "mcp_manager", None):
            return ""

        mcp_manager = self._tool_registry.mcp_manager
        all_servers = mcp_manager.list_servers()
        connected_servers = [name for name in all_servers if mcp_manager.is_connected(name)]

        if not connected_servers:
            return ""

        lines = ["\n## MCP Servers Connected\n\n"]

        for server_name in connected_servers:
            tools = mcp_manager.get_server_tools(server_name)
            lines.append(f"- **{server_name}**: {len(tools)} tools available\n")

        lines.append("\nUse `search_tools` to discover and enable MCP tools.\n")

        # Add configuration guidance
        lines.append("\n### MCP Server Configuration\n")
        lines.append("- `configure_mcp_server` - Add new server from preset\n")
        lines.append("- `list_mcp_presets` - Show available presets\n")

        return "".join(lines)

    def _build_mcp_config_section(self) -> str:
        """Render the MCP configuration section when no servers are connected."""
        lines = [
            "\n## MCP Server Configuration\n",
            "You can help users set up MCP (Model Context Protocol) servers for external integrations.\n\n",
            "Available tools:\n",
            "- `configure_mcp_server` - Configure a server from preset (github, postgres, slack, etc.)\n",
            "- `list_mcp_presets` - Show available server presets\n\n",
            "When users ask about setting up GitHub, database, Slack, or other integrations, ",
            "use these tools to configure the appropriate MCP server.\n",
        ]
        return "".join(lines)


class ThinkingPromptBuilder:
    """Constructs the THINKING mode system prompt for reasoning tasks.

    Used when thinking mode is enabled (Ctrl+Shift+T) to provide a specialized
    prompt that encourages step-by-step reasoning and explicit thought processes.

    Uses the same component architecture as SystemPromptBuilder for consistency.
    """

    def __init__(
        self,
        tool_registry: Any | None,
        working_dir: Any | None = None,
        skill_loader: "SkillLoader | None" = None,
        subagent_manager: "SubAgentManager | None" = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._working_dir = working_dir
        self._skill_loader = skill_loader
        self._subagent_manager = subagent_manager

    def build(self) -> str:
        """Build thinking-specialized system prompt from components."""
        sections = [
            self._build_core_identity(),
            self._build_environment(),
            self._build_skills_index(),
            self._build_mcp_section(),
        ]
        return "\n\n".join(filter(None, sections))

    def _build_core_identity(self) -> str:
        """Load thinking system prompt and inject agents."""
        prompt = load_prompt("thinking_system_prompt")
        return self._inject_available_agents(prompt)

    def _build_environment(self) -> str:
        """Build environment context section."""
        if not self._working_dir:
            return ""
        return f"# Working Directory\nCurrent directory: `{self._working_dir}`"

    def _build_skills_index(self) -> str:
        """Build available skills section from SkillLoader."""
        loader = self._skill_loader
        if not loader and self._tool_registry:
            loader = getattr(self._tool_registry, "_skill_loader", None)

        if not loader:
            return ""

        return loader.build_skills_index()

    def _build_mcp_section(self) -> str:
        """Build MCP servers section."""
        if not self._tool_registry or not getattr(self._tool_registry, "mcp_manager", None):
            return ""

        mcp_manager = self._tool_registry.mcp_manager
        all_servers = mcp_manager.list_servers()
        connected = [n for n in all_servers if mcp_manager.is_connected(n)]

        if not connected:
            return ""

        lines = ["## MCP Servers Connected"]
        for name in connected:
            tools = mcp_manager.get_server_tools(name)
            lines.append(f"- {name}: {len(tools)} tools (use search_tools to discover)")

        return "\n".join(lines)

    def _inject_available_agents(self, prompt: str) -> str:
        """Replace {available_agents} placeholder with actual subagent descriptions.

        This ensures the thinking model has the same subagent information as the
        main agent, enabling correct decisions about when to spawn vs use tools.
        """
        if "{available_agents}" not in prompt:
            return prompt

        # Try to get subagent_manager from multiple sources
        manager = self._subagent_manager
        if not manager and self._tool_registry:
            manager = getattr(self._tool_registry, "_subagent_manager", None)

        if not manager:
            return prompt.replace("{available_agents}", "(No subagents available)")

        available_types = manager.get_available_types()
        if not available_types:
            return prompt.replace("{available_agents}", "(No subagents available)")

        # Build the available agents list
        descriptions = manager.get_descriptions()
        agent_lines = []
        for name in available_types:
            desc = descriptions.get(name, "No description")
            agent_lines.append(f"- **{name}**: {desc}")

        available_agents_str = "\n".join(agent_lines)
        return prompt.replace("{available_agents}", available_agents_str)


class PlanningPromptBuilder:
    """Constructs the PLAN mode strategic planning prompt."""

    def __init__(self, working_dir: Any | None = None) -> None:
        self._working_dir = working_dir

    def build(self) -> str:
        """Return the planning prompt with working directory context."""
        prompt = load_prompt("planner_system_prompt")

        # Add working directory context
        if self._working_dir:
            prompt += f"\n\n# Working Directory Context\n\nYou are currently exploring the codebase in: `{self._working_dir}`\n\nUse this as the base directory for all file operations and searches.\n"

        return prompt
