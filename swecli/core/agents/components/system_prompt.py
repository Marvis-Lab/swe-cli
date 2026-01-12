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
        """Render the MCP tool section when servers are connected."""
        if not self._tool_registry or not getattr(self._tool_registry, "mcp_manager", None):
            return ""

        mcp_tools: Sequence[dict[str, Any]] = self._tool_registry.mcp_manager.get_all_tools()  # type: ignore[attr-defined]
        if not mcp_tools:
            return ""

        lines = ["\n## MCP Tools (Extended Capabilities)\n", "The following external tools are available through MCP servers:\n"]
        for tool in mcp_tools:
            tool_name = tool.get("name", "")
            description = tool.get("description", "")
            lines.append(f"- `{tool_name}` - {description}\n")

        lines.append("\nUse these MCP tools when they're relevant to the user's task.\n")

        # Add configuration guidance
        lines.append("\n### MCP Server Configuration\n")
        lines.append("You can help users set up new MCP servers using:\n")
        lines.append("- `configure_mcp_server` - Configure a server from preset (github, postgres, slack, etc.)\n")
        lines.append("- `list_mcp_presets` - Show available server presets\n")
        lines.append("\nWhen users ask about setting up GitHub, database, or other integrations, use these tools.\n")

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

        # Add MCP section if available (same as SystemPromptBuilder)
        if self._tool_registry and getattr(self._tool_registry, "mcp_manager", None):
            mcp_tools: Sequence[dict[str, Any]] = self._tool_registry.mcp_manager.get_all_tools()  # type: ignore[attr-defined]
            if mcp_tools:
                lines = ["\n## Available MCP Tools\n"]
                for tool in mcp_tools:
                    tool_name = tool.get("name", "")
                    description = tool.get("description", "")
                    lines.append(f"- `{tool_name}` - {description}\n")
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
