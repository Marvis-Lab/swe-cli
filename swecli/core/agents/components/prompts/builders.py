"""System prompt builders for OpenDev agents."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from swecli.core.agents.prompts import load_prompt

if TYPE_CHECKING:
    from swecli.core.skills import SkillLoader
    from swecli.core.agents.subagents.manager import SubAgentManager
    from .environment import EnvironmentContext


class SystemPromptBuilder:
    """Constructs the NORMAL mode system prompt with optional MCP tooling.

    Uses a component-based architecture for assembling the system prompt:
    - Core identity (from main_system_prompt.txt)
    - Environment context (working directory, git status, project structure)
    - Project instructions (SWECLI.md content)
    - Skills index (available skills for invoke_skill tool)
    - MCP section (connected servers)

    Note: Subagent information is included in the spawn_subagent tool schema,
    not in the system prompt.
    """

    def __init__(
        self,
        tool_registry: Any | None,
        working_dir: Any | None = None,
        skill_loader: "SkillLoader | None" = None,
        subagent_manager: "SubAgentManager | None" = None,
        env_context: "EnvironmentContext | None" = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._working_dir = working_dir
        self._skill_loader = skill_loader
        self._subagent_manager = subagent_manager
        self._env_context = env_context

    def build(self) -> str:
        """Build complete system prompt from components."""
        sections = [
            self._build_core_identity(),
            self._build_environment(),
            self._build_project_instructions(),
            self._build_skills_index(),
            self._build_mcp_section() or self._build_mcp_config_section(),
        ]
        return "\n\n".join(filter(None, sections))

    def _build_core_identity(self) -> str:
        """Load and return core identity from main_system_prompt.txt."""
        return load_prompt("main_system_prompt")

    def _build_environment(self) -> str:
        """Build environment context section."""
        if self._env_context:
            from .environment import (
                build_env_block,
                build_git_status_block,
                build_project_structure_block,
            )

            parts = [
                build_env_block(self._env_context),
                build_git_status_block(self._env_context),
                build_project_structure_block(self._env_context),
            ]
            return "\n\n".join(filter(None, parts))

        # Fallback: minimal working directory text
        if not self._working_dir:
            return ""
        return f"""# Working Directory Context

You are currently working in the directory: `{self._working_dir}`

When processing file paths without explicit directories (like `app.py` or `README.md`), assume they are located in the current working directory unless the user provides a specific path. Use relative paths from the working directory for file operations."""

    def _build_project_instructions(self) -> str:
        """Build project instructions section from SWECLI.md content."""
        if self._env_context:
            from .environment import build_project_instructions_block

            return build_project_instructions_block(self._env_context)
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


        return "".join(lines)

    def _build_mcp_config_section(self) -> str:
        """Render the MCP configuration section when no servers are connected."""
        lines = [
            "\n## MCP Server Configuration\n",
            "You can help users set up MCP (Model Context Protocol) servers "
            "for external integrations.\n\n",
            "When users ask about setting up an MCP server:\n",
            "1. Use `web_search` to find the MCP server package and docs\n",
            "2. Use `fetch_url` to read the server's README/documentation\n",
            "3. Read `~/.opendev/mcp.json` and add the server configuration\n",
            "4. Tell the user to connect with `/mcp connect <name>`\n",
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
        env_context: "EnvironmentContext | None" = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._working_dir = working_dir
        self._skill_loader = skill_loader
        self._subagent_manager = subagent_manager
        self._env_context = env_context

    def build(self) -> str:
        """Build thinking-specialized system prompt from components."""
        sections = [
            self._build_core_identity(),
            self._build_environment(),
            self._build_project_instructions(),
            self._build_skills_index(),
            self._build_mcp_section(),
        ]
        return "\n\n".join(filter(None, sections))

    def _build_core_identity(self) -> str:
        """Load thinking system prompt."""
        return load_prompt("thinking_system_prompt")

    def _build_environment(self) -> str:
        """Build environment context section."""
        if self._env_context:
            from .environment import (
                build_env_block,
                build_git_status_block,
                build_project_structure_block,
            )

            parts = [
                build_env_block(self._env_context),
                build_git_status_block(self._env_context),
                build_project_structure_block(self._env_context),
            ]
            return "\n\n".join(filter(None, parts))

        if not self._working_dir:
            return ""
        return f"# Working Directory\nCurrent directory: `{self._working_dir}`"

    def _build_project_instructions(self) -> str:
        """Build project instructions section from SWECLI.md content."""
        if self._env_context:
            from .environment import build_project_instructions_block

            return build_project_instructions_block(self._env_context)
        return ""

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


class PlanningPromptBuilder:
    """Constructs the PLAN mode strategic planning prompt."""

    def __init__(
        self,
        working_dir: Any | None = None,
        env_context: "EnvironmentContext | None" = None,
    ) -> None:
        self._working_dir = working_dir
        self._env_context = env_context

    def build(self) -> str:
        """Return the planning prompt with working directory context."""
        prompt = load_prompt("planner_system_prompt")

        # Add environment context
        env_section = self._build_environment()
        if env_section:
            prompt += "\n\n" + env_section

        # Add project instructions
        instructions = self._build_project_instructions()
        if instructions:
            prompt += "\n\n" + instructions

        return prompt

    def _build_environment(self) -> str:
        """Build environment context section."""
        if self._env_context:
            from .environment import (
                build_env_block,
                build_git_status_block,
                build_project_structure_block,
            )

            parts = [
                build_env_block(self._env_context),
                build_git_status_block(self._env_context),
                build_project_structure_block(self._env_context),
            ]
            return "\n\n".join(filter(None, parts))

        if not self._working_dir:
            return ""
        return (
            f"# Working Directory Context\n\n"
            f"You are currently exploring the codebase in: `{self._working_dir}`\n\n"
            f"Use this as the base directory for all file operations and searches.\n"
        )

    def _build_project_instructions(self) -> str:
        """Build project instructions section from SWECLI.md content."""
        if self._env_context:
            from .environment import build_project_instructions_block

            return build_project_instructions_block(self._env_context)
        return ""
