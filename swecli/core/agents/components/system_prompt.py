"""System prompt builders for SWE-CLI agents."""

from __future__ import annotations

from typing import Any, Sequence, Union

from swecli.core.agents.prompts import load_prompt


class SystemPromptBuilder:
    """Constructs the NORMAL mode system prompt with optional MCP tooling."""

    def __init__(self, tool_registry: Union[Any, None], working_dir: Union[Any, None] = None) -> None:
        self._tool_registry = tool_registry
        self._working_dir = working_dir

    def build(self) -> str:
        """Return the formatted system prompt string."""
        # Load base prompt from file
        prompt = load_prompt("main_system_prompt")

        # Replace {available_agents} placeholder with actual subagent list
        prompt = self._inject_available_agents(prompt)

        # Add working directory context
        if self._working_dir:
            prompt += f"\n\n# Working Directory Context\n\nYou are currently working in the directory: `{self._working_dir}`\n\nWhen processing file paths without explicit directories (like `app.py` or `README.md`), assume they are located in the current working directory unless the user provides a specific path. Use relative paths from the working directory for file operations.\n"

        # Add MCP section if available
        mcp_prompt = self._build_mcp_section()
        if mcp_prompt:
            prompt += mcp_prompt
        else:
            # Even without MCP tools, add configuration guidance
            prompt += self._build_mcp_config_section()

        return prompt

    def _inject_available_agents(self, prompt: str) -> str:
        """Replace {available_agents} placeholder with actual subagent descriptions."""
        if "{available_agents}" not in prompt:
            return prompt

        if not self._tool_registry:
            return prompt.replace("{available_agents}", "(No subagents available)")

        subagent_manager = getattr(self._tool_registry, "_subagent_manager", None)
        if not subagent_manager:
            return prompt.replace("{available_agents}", "(No subagents available)")

        available_types = subagent_manager.get_available_types()
        if not available_types:
            return prompt.replace("{available_agents}", "(No subagents available)")

        # Build the available agents list
        descriptions = subagent_manager.get_descriptions()
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
    """

    def __init__(self, tool_registry: Union[Any, None], working_dir: Union[Any, None] = None) -> None:
        self._tool_registry = tool_registry
        self._working_dir = working_dir

    def build(self) -> str:
        """Return the thinking-specialized system prompt."""
        prompt = load_prompt("thinking_system_prompt")

        # Add working directory context
        if self._working_dir:
            prompt += f"\n\n# Working Directory\nCurrent directory: `{self._working_dir}`\n"

        # Add MCP section if available - show servers only, not individual tools
        if self._tool_registry and getattr(self._tool_registry, "mcp_manager", None):
            mcp_manager = self._tool_registry.mcp_manager
            all_servers = mcp_manager.list_servers()
            connected = [n for n in all_servers if mcp_manager.is_connected(n)]
            if connected:
                lines = ["\n## MCP Servers Connected\n"]
                for name in connected:
                    tools = mcp_manager.get_server_tools(name)
                    lines.append(f"- {name}: {len(tools)} tools (use search_tools to discover)\n")
                prompt += "".join(lines)

        return prompt


class PlanningPromptBuilder:
    """Constructs the PLAN mode strategic planning prompt."""

    def __init__(self, working_dir: Union[Any, None] = None) -> None:
        self._working_dir = working_dir

    def build(self) -> str:
        """Return the planning prompt with working directory context."""
        prompt = load_prompt("planner_system_prompt")

        # Add working directory context
        if self._working_dir:
            prompt += f"\n\n# Working Directory Context\n\nYou are currently exploring the codebase in: `{self._working_dir}`\n\nUse this as the base directory for all file operations and searches.\n"

        return prompt
