"""Interactive REPL for SWE-CLI."""

from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel

from swecli.core.runtime.approval import ApprovalManager
from swecli.core.runtime import (
    ConfigManager,
    ModeManager,
    OperationMode,
)
from swecli.core.context_engineering.history import SessionManager, UndoManager
from swecli.core.runtime.monitoring import ErrorHandler
from swecli.core.runtime.services import RuntimeService
from swecli.models.message import ChatMessage, Role
from swecli.core.context_engineering.tools.implementations import (
    FileOperations,
    WriteTool,
    EditTool,
    BashTool,
)
from swecli.ui_textual.components.console_animations import Spinner
from swecli.ui_textual.components import StatusLine, NotificationCenter
from swecli.ui_textual.autocomplete import SwecliCompleter
from swecli.ui_textual.formatters_internal.output_formatter import OutputFormatter

# Command handlers
from swecli.repl.commands import (
    SessionCommands,
    ModeCommands,
    MCPCommands,
    HelpCommand,
    ConfigCommands,
    ToolCommands,
)

# UI components
from swecli.repl.ui import (
    MessagePrinter,
    InputFrame,
    PromptBuilder,
    Toolbar,
    ContextDisplay,
)

# Query processing
from swecli.repl.query_processor import QueryProcessor


class REPL:
    """Interactive REPL for AI-powered coding assistance."""

    def __init__(self, config_manager: ConfigManager, session_manager: SessionManager):
        """Initialize REPL.

        Args:
            config_manager: Configuration manager
            session_manager: Session manager
        """
        self.config_manager = config_manager
        self.session_manager = session_manager
        self.config = config_manager.get_config()
        self.console = Console()

        # Initialize tools and managers
        self._init_tools()
        self._init_managers()
        self._init_runtime_service()

        # Initialize UI
        self._init_ui_components()
        self._init_prompt_session()

        # Initialize command handlers
        self._init_command_handlers()

        # Initialize query processor
        self._init_query_processor()

        self.running = True

    def _init_tools(self):
        """Initialize file operation and command tools."""
        from swecli.core.context_engineering.tools.implementations import (
            WebFetchTool,
            OpenBrowserTool,
            VLMTool,
            WebScreenshotTool,
        )
        from swecli.core.context_engineering.mcp.manager import MCPManager

        self.file_ops = FileOperations(self.config, self.config_manager.working_dir)
        self.write_tool = WriteTool(self.config, self.config_manager.working_dir)
        self.edit_tool = EditTool(self.config, self.config_manager.working_dir)
        self.bash_tool = BashTool(self.config, self.config_manager.working_dir)
        self.web_fetch_tool = WebFetchTool(self.config, self.config_manager.working_dir)
        self.open_browser_tool = OpenBrowserTool(self.config, self.config_manager.working_dir)
        self.vlm_tool = VLMTool(self.config, self.config_manager.working_dir)
        self.web_screenshot_tool = WebScreenshotTool(self.config, self.config_manager.working_dir)
        self.mcp_manager = MCPManager(working_dir=self.config_manager.working_dir)

    def _init_managers(self):
        """Initialize operation managers."""
        self.mode_manager = ModeManager()
        self.approval_manager = ApprovalManager(self.console)
        self.error_handler = ErrorHandler(self.console)
        self.undo_manager = UndoManager(self.config.max_undo_history)

    def _init_runtime_service(self):
        """Initialize runtime service with tool registry and agents."""
        self.runtime_service = RuntimeService(self.config_manager, self.mode_manager)
        self.runtime_suite = self.runtime_service.build_suite(
            file_ops=self.file_ops,
            write_tool=self.write_tool,
            edit_tool=self.edit_tool,
            bash_tool=self.bash_tool,
            web_fetch_tool=self.web_fetch_tool,
            open_browser_tool=self.open_browser_tool,
            vlm_tool=self.vlm_tool,
            web_screenshot_tool=self.web_screenshot_tool,
            mcp_manager=self.mcp_manager,
        )

        self.tool_registry = self.runtime_suite.tool_registry
        self.normal_agent = self.runtime_suite.agents.normal
        self.planning_agent = self.runtime_suite.agents.planning
        self.agent = self.normal_agent  # Default to normal agent

    def _init_ui_components(self):
        """Initialize UI components and state."""
        # UI Components
        self.spinner = Spinner(self.console)
        self.status_line = StatusLine(self.console)
        self.output_formatter = OutputFormatter(self.console, use_claude_style=True)
        self._notification_center = NotificationCenter(self.console)

        # UI state trackers
        self._last_latency_ms: Optional[int] = None
        self._context_sidebar_visible = False
        self._last_prompt: str = ""
        self._last_operation_summary: str = "—"
        self._last_error: Optional[str] = None
        self._key_bindings = self._build_key_bindings()

        # Message printer and input frame
        self.message_printer = MessagePrinter(self.console)
        self.input_frame = InputFrame(self.console)
        self.prompt_builder = PromptBuilder()
        self.toolbar = Toolbar(self.mode_manager, self.session_manager, self.config)
        self.context_display = ContextDisplay(
            self.console,
            self.mode_manager,
            self.session_manager,
            self.config_manager,
            self._notification_center,
        )

    def _init_prompt_session(self):
        """Initialize prompt session with history and autocomplete."""
        # Setup prompt session with history
        history_file = Path(self.config.swecli_dir).expanduser() / "history.txt"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        # Create autocomplete for @ mentions and / commands
        self.completer = SwecliCompleter(working_dir=self.config_manager.working_dir)

        # Elegant autocomplete styling
        autocomplete_style = Style.from_dict({
            'completion-menu': 'bg:#000000',
            'completion-menu.completion': '#FFFFFF',
            'completion-menu.completion.current': 'bg:#2A2A2A #FFFFFF',
            'completion-menu.meta': '#808080',
            'completion-menu.completion.current.meta': '#A0A0A0',
            'mode-normal': 'bold #ff9f43',
            'mode-plan': 'bold #2ecc71',
            'toolbar-text': '#aaaaaa',
        })

        self.prompt_session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_file)),
            completer=self.completer,
            complete_while_typing=True,
            key_bindings=self._key_bindings,
            style=autocomplete_style,
            bottom_toolbar=self.toolbar.build_tokens,
        )

    def _init_command_handlers(self):
        """Initialize slash command handlers."""
        self.session_commands = SessionCommands(
            self.console,
            self.session_manager,
            self.config_manager,
        )

        self.mode_commands = ModeCommands(
            self.console,
            self.mode_manager,
            self.undo_manager,
            self.approval_manager,
        )

        self.config_commands = ConfigCommands(
            self.console,
            self.config_manager,
            chat_app=None,  # Will be set by ReplChat
        )

        self.mcp_commands = MCPCommands(
            self.console,
            self.mcp_manager,
            refresh_runtime_callback=self._refresh_runtime_tooling,
            agent=self.agent,
        )

        self.tool_commands = ToolCommands(
            console=self.console,
            config=self.config,
            config_manager=self.config_manager,
            mode_manager=self.mode_manager,
            approval_manager=self.approval_manager,
            undo_manager=self.undo_manager,
            session_manager=self.session_manager,
            mcp_manager=self.mcp_manager,
            runtime_suite=self.runtime_suite,
            bash_tool=self.bash_tool,
            error_handler=self.error_handler,
            agent=self.agent,
        )

        self.help_command = HelpCommand(
            self.console,
            self.mode_manager,
        )

    def _init_query_processor(self):
        """Initialize query processor for AI interactions."""
        self.query_processor = QueryProcessor(
            self.console,
            self.session_manager,
            self.config,
            self.config_manager,
            self.mode_manager,
            self.file_ops,
            self.output_formatter,
            self.status_line,
            self._print_markdown_message,
        )
        self.query_processor.set_notification_center(self._notification_center)

    def _refresh_runtime_tooling(self) -> None:
        """Refresh tool registry and agent metadata after MCP changes."""
        if hasattr(self.tool_registry, "set_mcp_manager"):
            self.tool_registry.set_mcp_manager(self.mcp_manager)
        self.runtime_suite.refresh_agents()

    def rebuild_agents(self) -> None:
        """Rebuild agents with updated configuration (e.g., after model/provider change).

        This is needed when the model provider changes, as the HTTP client
        needs to use the new provider's API key.
        """
        # Refresh config
        self.config = self.config_manager.get_config()

        # Rebuild agents with new config
        self.runtime_suite.rebuild_agents(
            self.config,
            self.mode_manager,
            self.config_manager.working_dir,
        )

        # Update agent references
        self.normal_agent = self.runtime_suite.agents.normal
        self.planning_agent = self.runtime_suite.agents.planning

        # Update current agent based on mode
        if self.mode_manager.current_mode == OperationMode.PLAN:
            self.agent = self.planning_agent
        else:
            self.agent = self.normal_agent

    def _build_key_bindings(self) -> KeyBindings:
        """Configure prompt key bindings for high-speed workflows."""
        kb = KeyBindings()

        @kb.add("s-tab")
        def _(event) -> None:
            new_mode = (
                OperationMode.PLAN
                if self.mode_manager.current_mode == OperationMode.NORMAL
                else OperationMode.NORMAL
            )
            self.mode_manager.set_mode(new_mode)

            if hasattr(self, "approval_manager"):
                self.approval_manager.reset_auto_approve()

            # Switch agent based on mode
            if new_mode == OperationMode.PLAN:
                self.agent = self.planning_agent
            else:
                self.agent = self.normal_agent

            self._notify(
                f"Switched to {new_mode.value.upper()} mode.",
                level="info",
                toast=False,
            )
            event.app.invalidate()

        return kb

    def _print_markdown_message(
        self,
        content: str,
        *,
        symbol: str = "⏺",
    ) -> None:
        """Render assistant content as simple plain text with a leading symbol."""
        self.message_printer.print_markdown_message(content, symbol=symbol)

    def _notify(self, message: str, level: str = "info", *, toast: bool = True) -> None:
        """Record a notification and optionally display a toast."""
        title_map = {
            "info": ("Info", "cyan"),
            "warning": ("Warning", "yellow"),
            "error": ("Error", "red"),
        }
        title, style = title_map.get(level, ("Info", "cyan"))
        self._notification_center.add(level, message)
        if toast:
            self.console.print(Panel(message, title=title, border_style=style, expand=False))

    def _show_notifications(self) -> None:
        """Render the notification center."""
        self.console.print()
        self._notification_center.render()

    def _render_context_overview(self) -> None:
        """Render a compact context sidebar above the prompt."""
        self.context_display.render(
            last_prompt=self._last_prompt,
            last_operation_summary=self._last_operation_summary,
            last_error=self._last_error,
        )

    def start(self) -> None:
        """Start the REPL loop."""
        self._print_welcome()

        # Connect to enabled MCP servers
        self._connect_mcp_servers()

        # Load context files
        context_files = self.config_manager.load_context_files()
        if context_files:
            system_message = ChatMessage(
                role=Role.SYSTEM,
                content="\n\n".join(context_files),
            )
            self.session_manager.add_message(system_message, self.config.auto_save_interval)

        while self.running:
            try:
                if self._context_sidebar_visible:
                    self._render_context_overview()

                self.input_frame.print_top()
                user_input = self.prompt_session.prompt(self.prompt_builder.build_tokens())
                self.input_frame.print_bottom()

                if not user_input.strip():
                    continue

                # Check for slash commands
                if user_input.startswith("/"):
                    self._handle_command(user_input)
                    continue

                self._last_prompt = user_input.strip()

                # Process as regular query
                self._process_query(user_input)

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Exiting...[/yellow]")
                self.running = False
                break
            except EOFError:
                break

        self._cleanup()

    def _print_welcome(self) -> None:
        """Print compact welcome banner using shared welcome module."""
        from swecli.ui_textual.components import WelcomeMessage

        # Generate welcome content using shared module
        welcome_lines = WelcomeMessage.generate_full_welcome(
            current_mode=self.mode_manager.current_mode,
            working_dir=self.config_manager.working_dir,
        )

        # Print each line with Rich formatting
        for line in welcome_lines:
            # Apply color based on content
            if line.startswith("╔") or line.startswith("║") or line.startswith("╚"):
                self.console.print(f"[white]{line}[/white]")
            elif "Essential Commands:" in line:
                self.console.print(f"[bold white]{line}[/bold white]")
            elif "/help" in line or "/mode" in line:
                styled = line.replace("/help", "[cyan]/help[/cyan]")
                styled = styled.replace("/mode plan", "[cyan]/mode plan[/cyan]")
                styled = styled.replace("/mode normal", "[cyan]/mode normal[/cyan]")
                self.console.print(styled)
            elif "Shortcuts:" in line:
                styled = f"[bold white]{line.split(':')[0]}:[/bold white]"
                rest = line.split(':', 1)[1] if ':' in line else ""
                styled += rest.replace("Shift+Tab", "[yellow]Shift+Tab[/yellow]")
                styled = styled.replace("@file", "[yellow]@file[/yellow]")
                styled = styled.replace("↑↓", "[yellow]↑↓[/yellow]")
                self.console.print(styled)
            elif "Session:" in line:
                mode = self.mode_manager.current_mode.value.upper()
                mode_color = "green" if mode == "PLAN" else "yellow"
                styled = f"[bold white]{line.split(':')[0]}:[/bold white]"
                rest = line.split(':', 1)[1] if ':' in line else ""
                if mode in rest:
                    rest = rest.replace(mode, f"[{mode_color}]{mode}[/{mode_color}]")
                styled += rest
                self.console.print(styled)
            else:
                self.console.print(line)


    def _process_query(self, query: str) -> None:
        """Process a user query with AI using ReAct pattern.

        Args:
            query: User query
        """
        # Delegate to query processor
        result = self.query_processor.process_query(
            query,
            self.agent,
            self.tool_registry,
            self.approval_manager,
            self.undo_manager,
        )

        # Update state from query processor results
        self._last_operation_summary, self._last_error, self._last_latency_ms = result

    def _process_query_with_callback(self, query: str, ui_callback) -> None:
        """Process a user query with AI using ReAct pattern with UI callback for real-time updates.

        Args:
            query: User query
            ui_callback: UI callback for real-time tool display
        """
        # Delegate to query processor with callback
        if hasattr(self.query_processor, 'process_query_with_callback'):
            result = self.query_processor.process_query_with_callback(
                query,
                self.agent,
                self.tool_registry,
                self.approval_manager,
                self.undo_manager,
                ui_callback,
            )
        else:
            # Fallback to normal processing if callback method doesn't exist
            result = self.query_processor.process_query(
                query,
                self.agent,
                self.tool_registry,
                self.approval_manager,
                self.undo_manager,
            )

        # Update state from query processor results
        self._last_operation_summary, self._last_error, self._last_latency_ms = result

    def _handle_command(self, command: str) -> None:
        """Handle slash commands.

        Args:
            command: Command string (including /)
        """
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Route to command handlers
        if cmd == "/help":
            self.help_command.handle(args)
        elif cmd == "/exit" or cmd == "/quit":
            self.running = False
        elif cmd == "/clear":
            self.session_commands.clear()
        elif cmd == "/sessions":
            self.session_commands.list_sessions()
        elif cmd == "/resume":
            self.session_commands.resume(args)
        elif cmd == "/changed-files" or cmd == "/changes":
            self.session_commands.changed_files()
        elif cmd == "/mode":
            result = self.mode_commands.switch_mode(args)
            # Sync agent after mode switch
            if result.success and result.data:
                new_mode = result.data
                if new_mode == OperationMode.PLAN:
                    self.agent = self.planning_agent
                else:
                    self.agent = self.normal_agent
        elif cmd == "/history":
            self.mode_commands.show_history()
        elif cmd == "/models":
            self.config_commands.show_model_selector()
        elif cmd == "/mcp":
            self.mcp_commands.handle(args)
        elif cmd == "/init":
            self.tool_commands.init_codebase(command)
        elif cmd == "/run":
            self.tool_commands.run_command(args)
        elif cmd == "/resolve-issue":
            self.tool_commands.resolve_issue(command)
        elif cmd == "/paper2code":
            self.tool_commands.paper2code(command)
        else:
            self.console.print(f"[cyan]⏺[/cyan] {cmd}")
            self.console.print(f"  ⎿  [red]Unknown command[/red]")
            self.console.print("  ⎿  Type /help for available commands")


    def _connect_mcp_servers(self) -> None:
        """Connect to enabled MCP servers on startup asynchronously."""
        import threading

        def connect_in_background():
            """Background thread to connect to MCP servers."""
            try:
                # Get connection results using synchronous wrapper
                results = self.mcp_manager.connect_enabled_servers_sync()

                if results:
                    # Silently connect - no messages
                    self._refresh_runtime_tooling()
            except Exception:
                # Silently fail - user can check with /mcp list
                pass

        # Start connection in background thread - silently
        thread = threading.Thread(target=connect_in_background, daemon=True)
        thread.start()

    def _cleanup(self) -> None:
        """Cleanup resources."""
        # Disconnect from MCP servers using manager's shared loop
        try:
            self.mcp_manager.disconnect_all_sync()
        except Exception as e:
            self.console.print(f"[yellow]Warning: Error disconnecting MCP servers: {e}[/yellow]")

        # Save current session
        if self.session_manager.current_session:
            self.session_manager.save_session()

        # No cleanup needed for Pydantic AI agent
        self.console.print("\n[cyan]Goodbye![/cyan]")
