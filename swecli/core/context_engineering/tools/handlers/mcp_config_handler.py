"""Handler for MCP server configuration tools."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from swecli.core.context_engineering.mcp.presets import (
    get_preset,
    list_presets,
    search_presets,
    check_required_env,
    get_env_setup_instructions,
    get_categories,
)

if TYPE_CHECKING:
    from swecli.core.context_engineering.mcp.manager import MCPManager


class MCPConfigHandler:
    """Handler for MCP server configuration tools."""

    def __init__(self, mcp_manager: "MCPManager | None" = None):
        """Initialize MCP config handler.

        Args:
            mcp_manager: MCP manager instance
        """
        self._mcp_manager = mcp_manager

    def set_mcp_manager(self, mcp_manager: "MCPManager | None") -> None:
        """Set the MCP manager.

        Args:
            mcp_manager: MCP manager instance
        """
        self._mcp_manager = mcp_manager

    def configure_mcp_server(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Configure an MCP server from a preset.

        Args:
            arguments: Tool arguments containing:
                - preset_name: Name of the preset (e.g., "github")
                - server_name: Optional custom name for the server
                - auto_connect: Whether to connect immediately (default True)
            context: Tool execution context

        Returns:
            Result dict with success status and configuration details
        """
        if not self._mcp_manager:
            return {
                "success": False,
                "error": "MCP Manager not available",
                "output": None,
            }

        preset_name = arguments.get("preset_name", "").lower()
        server_name = arguments.get("server_name") or preset_name
        auto_connect = arguments.get("auto_connect", True)

        # Get preset
        preset = get_preset(preset_name)
        if not preset:
            # Try to find similar presets
            matches = search_presets(preset_name)
            if matches:
                suggestions = ", ".join(p.id for p in matches[:5])
                return {
                    "success": False,
                    "error": f"Unknown preset: '{preset_name}'. Did you mean: {suggestions}?",
                    "output": None,
                }
            available = ", ".join(p.id for p in list_presets())
            return {
                "success": False,
                "error": f"Unknown preset: '{preset_name}'. Available presets: {available}",
                "output": None,
            }

        # Check if already configured
        config = self._mcp_manager.get_config()
        if server_name in config.mcp_servers:
            # Already exists, check if connected
            if self._mcp_manager.is_connected(server_name):
                return {
                    "success": True,
                    "output": f"MCP server '{server_name}' is already configured and connected.",
                    "already_configured": True,
                }
            else:
                # Configured but not connected, try to connect
                if auto_connect:
                    try:
                        connected = self._mcp_manager.connect_sync(server_name)
                        if connected:
                            return {
                                "success": True,
                                "output": f"MCP server '{server_name}' was already configured. Connected successfully.",
                                "already_configured": True,
                                "connected": True,
                            }
                    except Exception as e:
                        pass  # Will show env setup instructions below

        # Check required environment variables
        env_status = check_required_env(preset)
        missing_env = [var for var, is_set in env_status.items() if not is_set]

        # Add server configuration
        self._mcp_manager.add_server(
            name=server_name,
            command=preset.command,
            args=preset.args,
            env=preset.env,
            transport=preset.transport,
            url=preset.url or None,
            headers=preset.headers,
        )

        result = {
            "success": True,
            "output": f"MCP server '{server_name}' configured successfully.",
            "server_name": server_name,
            "preset": preset.id,
            "description": preset.description,
            "docs_url": preset.docs_url,
        }

        # If env vars are missing, include setup instructions
        if missing_env:
            instructions = get_env_setup_instructions(preset)
            result["missing_env_vars"] = missing_env
            result["setup_instructions"] = instructions
            result["output"] += (
                f"\n\nNote: The following environment variables are not set: {', '.join(missing_env)}\n\n"
                f"{instructions}\n"
                f"After setting them, run `/mcp connect {server_name}` to connect."
            )
        else:
            # All env vars set, try to connect
            if auto_connect:
                try:
                    connected = self._mcp_manager.connect_sync(server_name)
                    if connected:
                        result["connected"] = True
                        result["output"] += " Server is now connected and ready to use."

                        # Get available tools
                        tools = self._mcp_manager.get_server_tools(server_name)
                        if tools:
                            tool_names = [t.get("name", "").split("__")[-1] for t in tools]
                            result["tools"] = tool_names
                            result["output"] += f"\n\nAvailable tools: {', '.join(tool_names[:10])}"
                            if len(tool_names) > 10:
                                result["output"] += f" (and {len(tool_names) - 10} more)"
                    else:
                        result["connected"] = False
                        result["output"] += "\n\nWarning: Failed to connect. Check your environment variables."
                except Exception as e:
                    result["connected"] = False
                    result["connection_error"] = str(e)
                    result["output"] += f"\n\nConnection failed: {e}"

        return result

    def list_mcp_presets(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """List available MCP server presets.

        Args:
            arguments: Tool arguments containing:
                - category: Optional category filter
                - search: Optional search query
            context: Tool execution context

        Returns:
            Result dict with list of presets
        """
        category = arguments.get("category")
        search_query = arguments.get("search")

        if search_query:
            presets = search_presets(search_query)
        elif category:
            presets = list_presets(category)
        else:
            presets = list_presets()

        if not presets:
            return {
                "success": True,
                "output": "No presets found matching your criteria.",
                "presets": [],
            }

        # Format presets for output
        preset_list = []
        output_lines = ["Available MCP Server Presets:\n"]

        categories_shown = set()
        current_category = None

        # Sort by category
        presets_sorted = sorted(presets, key=lambda p: (p.category, p.name))

        for preset in presets_sorted:
            if preset.category != current_category:
                current_category = preset.category
                if current_category not in categories_shown:
                    output_lines.append(f"\n## {current_category.title()}")
                    categories_shown.add(current_category)

            # Check if configured and connected
            status = ""
            if self._mcp_manager:
                config = self._mcp_manager.get_config()
                if preset.id in config.mcp_servers:
                    if self._mcp_manager.is_connected(preset.id):
                        status = " [connected]"
                    else:
                        status = " [configured]"

            output_lines.append(f"- **{preset.id}**{status}: {preset.description}")

            preset_list.append({
                "id": preset.id,
                "name": preset.name,
                "description": preset.description,
                "category": preset.category,
                "required_env": preset.required_env,
            })

        output_lines.append(
            "\n\nTo configure a preset, use: configure_mcp_server(preset_name='...')"
        )

        return {
            "success": True,
            "output": "\n".join(output_lines),
            "presets": preset_list,
            "categories": list(get_categories()),
        }
