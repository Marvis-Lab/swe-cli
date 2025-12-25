"""MCP command handling for the Textual chat app."""

from __future__ import annotations

import shlex
import threading
import time
from concurrent.futures import Future
from typing import TYPE_CHECKING

from rich.text import Text

if TYPE_CHECKING:  # pragma: no cover
    from swecli.ui_textual.chat_app import SWECLIChatApp
    from swecli.repl.repl import REPL


class MCPCommandController:
    """Handle MCP-related slash commands and auto-connection."""

    def __init__(self, app: "SWECLIChatApp", repl: "REPL") -> None:
        """Initialize the MCP command controller.

        Args:
            app: The Textual chat application
            repl: The REPL instance with MCP manager
        """
        self.app = app
        self.repl = repl
        self._loop = getattr(app, '_loop', None)

    def handle_connect(self, command: str) -> None:
        """Handle /mcp connect command asynchronously with spinner.

        Args:
            command: The full command (e.g., "/mcp connect github")
        """
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.strip().split()

        if len(parts) < 3:
            self.app.conversation.add_error("Usage: /mcp connect <server_name>")
            return

        server_name = parts[2]
        mcp_manager = getattr(self.repl, "mcp_manager", None)

        if not mcp_manager:
            self.app.conversation.add_error("MCP manager not available")
            return

        # Check if already connected
        if mcp_manager.is_connected(server_name):
            tools = mcp_manager.get_server_tools(server_name)
            # Create tool call display with green bullet
            display = Text()
            display.append("⏺", style="green bold")
            display.append(f" MCP ({server_name}) (0s)")
            self.app.conversation.add_tool_call(display)
            self.app.conversation.stop_tool_execution()
            self.app.conversation.add_tool_result(
                f"Already connected to {server_name} ({len(tools)} tools available)"
            )
            return

        # Add tool call and start spinner (must block to ensure timer is set up)
        future = Future()

        def start_tool_call():
            display = Text(f"MCP ({server_name})")
            self.app.conversation.add_tool_call(display)
            self.app.conversation.start_tool_execution()

        # Use blocking call to ensure spinner timer is fully set up before continuing
        def wrapper():
            try:
                start_tool_call()
                future.set_result(None)
            except Exception as e:
                future.set_exception(e)

        if hasattr(self.app, 'call_from_thread'):
            self.app.call_from_thread(wrapper)
            try:
                future.result(timeout=5.0)
            except Exception:
                pass
        else:
            start_tool_call()

        # Run connection in background thread
        start_time = time.monotonic()

        def handle_result(success: bool):
            """Handle connection result in main thread."""
            def finalize():
                # Stop spinner first
                if hasattr(self.app.conversation, 'stop_tool_execution'):
                    self.app.conversation.stop_tool_execution()

                # Then show result
                elapsed = int(time.monotonic() - start_time)
                if success:
                    tools = mcp_manager.get_server_tools(server_name)
                    # Green checkmark for success
                    result_text = f"✓ Connected to {server_name} ({len(tools)} tools available)"
                    self.app.conversation.add_tool_result(result_text)
                else:
                    # Red X for failure
                    result_text = f"❌ Failed to connect to {server_name}"
                    self.app.conversation.add_tool_result(result_text)

            # Stop spinner and show result
            if hasattr(self.app, 'call_from_thread'):
                self.app.call_from_thread(finalize)
            elif self._loop:
                self._loop.call_soon_threadsafe(finalize)
            else:
                finalize()

            # Refresh runtime tooling AFTER showing result (don't block spinner)
            if success and hasattr(self.repl, '_refresh_runtime_tooling'):
                self.repl._refresh_runtime_tooling()

        def connect_thread():
            try:
                success = mcp_manager.connect_sync(server_name)
                handle_result(success)
            except Exception as e:
                # Stop spinner on error
                def stop_and_error():
                    if hasattr(self.app.conversation, 'stop_tool_execution'):
                        self.app.conversation.stop_tool_execution()
                    elapsed = int(time.monotonic() - start_time)
                    result_text = f"❌ Error: {str(e)}"
                    self.app.conversation.add_tool_result(result_text)

                if hasattr(self.app, 'call_from_thread'):
                    self.app.call_from_thread(stop_and_error)
                else:
                    stop_and_error()

        thread = threading.Thread(target=connect_thread, daemon=True)
        thread.start()

    def handle_view(self, command: str) -> None:
        """Handle /mcp view command to show MCP server modal.

        Args:
            command: The full command (e.g., "/mcp view")
        """
        # Import here to avoid circular dependency
        from swecli.ui_textual.modals.mcp_viewer_modal import MCPViewerModal

        mcp_manager = getattr(self.repl, "mcp_manager", None)
        if not mcp_manager:
            if hasattr(self.app, "conversation"):
                self.app.conversation.add_error("MCP manager not available")
            return

        # Get MCP servers data
        mcp_data = self._get_mcp_servers_data(mcp_manager)

        # Show modal
        modal = MCPViewerModal(mcp_data)
        self.app.push_screen(modal)

    def _get_mcp_servers_data(self, mcp_manager) -> list[dict]:
        """Get MCP servers data for the viewer modal.

        Args:
            mcp_manager: The MCP manager instance

        Returns:
            List of server data dictionaries
        """
        servers = []
        if hasattr(mcp_manager, "list_servers"):
            for server_name in mcp_manager.list_servers():
                connected = mcp_manager.is_connected(server_name)
                tools = mcp_manager.get_server_tools(server_name) if connected else []
                servers.append({
                    "name": server_name,
                    "connected": connected,
                    "tool_count": len(tools),
                    "tools": tools
                })
        return servers

    def notify_manual_connect(self, enqueue_console_text_callback) -> None:
        """Notify user about manual MCP connection.

        Args:
            enqueue_console_text_callback: Callback to enqueue console text
        """
        mcp_manager = getattr(self.repl, "mcp_manager", None)
        if not mcp_manager:
            return

        if hasattr(mcp_manager, "list_servers"):
            server_names = mcp_manager.list_servers()
            if server_names:
                enqueue_console_text_callback(
                    f"⏺ MCP servers configured: {', '.join(server_names)}\n"
                    f"  ⎿  Use [bold cyan]/mcp connect <server>[/bold cyan] to connect"
                )
        else:
            enqueue_console_text_callback(
                "⏺ MCP manager available\n"
                "  ⎿  Use [bold cyan]/mcp connect <server>[/bold cyan] to connect"
            )

    def start_auto_connect_thread(self, force: bool = False) -> None:
        """Start MCP auto-connection in a background thread.

        Args:
            force: Whether to force connection even if already attempted
        """
        if not force and hasattr(self, "_mcp_connect_attempted"):
            return
        self._mcp_connect_attempted = True

        thread = threading.Thread(target=self._launch_auto_connect, daemon=True)
        thread.start()

    def _launch_auto_connect(self) -> None:
        """Launch MCP auto-connection for all configured servers."""
        import time

        mcp_manager = getattr(self.repl, "mcp_manager", None)
        if not mcp_manager:
            return

        if not hasattr(mcp_manager, "list_servers"):
            return

        server_names = mcp_manager.list_servers()
        if not server_names:
            return

        for server_name in server_names:
            if mcp_manager.is_connected(server_name):
                continue

            start = time.monotonic()
            success = mcp_manager.connect_sync(server_name)
            elapsed = int(time.monotonic() - start)

            if success:
                tools = mcp_manager.get_server_tools(server_name)
                message = f"[green]⏺[/green] MCP ({server_name}) ({elapsed}s)\n  ⎿  Connected ({len(tools)} tools)"
            else:
                message = f"[red]⏺[/red] MCP ({server_name}) ({elapsed}s)\n  ⎿  ❌ Connection failed"

            # Use _enqueue_console_text from runner if available
            if hasattr(self, "_enqueue_console_text_callback"):
                self._enqueue_console_text_callback(message)

        # Refresh tools after all connections
        if hasattr(self.repl, "_refresh_runtime_tooling"):
            self.repl._refresh_runtime_tooling()


__all__ = ["MCPCommandController"]
