"""Command handlers for tool-related commands (/init)."""

from pathlib import Path
from typing import Any

from rich.console import Console

from swecli.core.runtime.approval import ApprovalManager
from swecli.core.runtime import ModeManager
from swecli.core.context_engineering.history import SessionManager, UndoManager
from swecli.models.agent_deps import AgentDependencies
from swecli.repl.commands.base import CommandHandler, CommandResult


class ToolCommands(CommandHandler):
    """Handler for tool-related commands."""

    def __init__(
        self,
        console: Console,
        config: Any,
        config_manager: Any,
        mode_manager: ModeManager,
        approval_manager: ApprovalManager,
        undo_manager: UndoManager,
        session_manager: SessionManager,
        mcp_manager: Any,
        runtime_suite: Any,
        bash_tool: Any,
        error_handler: Any,
        agent: Any,
    ):
        """Initialize tool commands handler.

        Args:
            console: Rich console for output
            config: Configuration object
            config_manager: Configuration manager
            mode_manager: Mode manager
            approval_manager: Approval manager
            undo_manager: Undo manager
            session_manager: Session manager
            mcp_manager: MCP manager
            runtime_suite: Runtime suite containing agents
            bash_tool: Bash tool for /run command
            error_handler: Error handler
            agent: Current agent
        """
        super().__init__(console)
        self.config = config
        self.config_manager = config_manager
        self.mode_manager = mode_manager
        self.approval_manager = approval_manager
        self.undo_manager = undo_manager
        self.session_manager = session_manager
        self.mcp_manager = mcp_manager
        self.runtime_suite = runtime_suite
        self.bash_tool = bash_tool
        self.error_handler = error_handler
        self.agent = agent

    def handle(self, args: str) -> CommandResult:
        """Handle generic command - not used as this handler supports multiple commands."""
        return CommandResult(success=False, message="Use specific methods for each command")

    def init_codebase(self, command: str) -> None:
        """Handle /init command to analyze codebase and generate AGENTS.md.

        Args:
            command: The full command string (e.g., "/init" or "/init /path/to/project")
        """
        from swecli.commands.init_command import InitCommandHandler

        # Create handler
        handler = InitCommandHandler(self.agent, self.console)

        # Parse arguments
        try:
            args = handler.parse_args(command)
        except Exception as e:
            self.print_command_header("init")
            self.print_error(f"Error parsing command: {e}")
            return

        # Create dependencies
        deps = AgentDependencies(
            mode_manager=self.mode_manager,
            approval_manager=self.approval_manager,
            undo_manager=self.undo_manager,
            session_manager=self.session_manager,
            working_dir=Path.cwd(),
            console=self.console,
            config=self.config,
        )

        # Execute init command
        try:
            result = handler.execute(args, deps)

            self.print_command_header("init")
            if result["success"]:
                self.print_success(result['message'])

                # Show summary of what was generated
                if "content" in result:
                    self.console.print(f"  ⎿  [dim]{result['content']}[/dim]")
            else:
                self.print_error(result['message'])

        except Exception as e:
            self.print_command_header("init")
            self.print_error(f"Error during initialization: {e}")
            import traceback
            traceback.print_exc()
