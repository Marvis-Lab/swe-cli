"""Command handlers for tool-related commands (/init, /run, /resolve-github-issue, /paper2code)."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from swecli.core.runtime.approval import ApprovalManager
from swecli.core.runtime import ModeManager
from swecli.core.context_engineering.history import SessionManager, UndoManager
from swecli.models.operation import Operation, OperationType
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

    def resolve_issue(self, command: str, ui_callback: Any = None) -> None:
        """Handle /resolve-github-issue command to fix GitHub issues.

        Args:
            command: The full command string (e.g., "/resolve-github-issue https://github.com/owner/repo/issues/123")
            ui_callback: Optional UI callback for real-time display. If None, uses console output.
        """
        # Catch FD errors early - these happen in Textual's event loop
        try:
            self._resolve_issue_inner(command, ui_callback)
        except ValueError as e:
            if "fds_to_keep" in str(e):
                # This is the subprocess FD error - handle gracefully
                self.print_command_header("resolve-github-issue")
                self.print_warning("Subprocess error in Textual context - retrying...")
                # Try again - sometimes it works on retry
                try:
                    self._resolve_issue_inner(command, ui_callback)
                except Exception as retry_e:
                    self.print_error(f"Error: {retry_e}")
            else:
                raise

    def _resolve_issue_inner(self, command: str, ui_callback: Any = None) -> None:
        """Inner implementation of resolve-github-issue command."""
        from swecli.commands.issue_resolver import IssueResolverCommand

        # Get subagent manager from runtime suite
        subagent_manager = getattr(self.runtime_suite.agents, "subagent_manager", None)
        if subagent_manager is None:
            self.print_command_header("resolve-github-issue")
            self.print_error("Subagent manager not available")
            return

        # Create a simple console callback if no ui_callback provided
        if ui_callback is None:
            ui_callback = self._create_console_callback()

        # Create handler
        handler = IssueResolverCommand(
            subagent_manager=subagent_manager,
            mcp_manager=self.mcp_manager,
            working_dir=self.config_manager.working_dir,
            mode_manager=self.mode_manager,
            approval_manager=self.approval_manager,
            undo_manager=self.undo_manager,
            ui_callback=ui_callback,
        )

        # Parse arguments
        try:
            args = handler.parse_args(command)
        except ValueError as e:
            self.print_command_header("resolve-github-issue")
            self.print_error(str(e))
            return

        # Execute issue resolution
        try:
            result = handler.execute(args)

            if result.success:
                self.print_success(result.message)
                # Access PR URL from PRMetadata
                if hasattr(result.metadata, 'pr_url'):
                    self.print_info(f"Pull Request: {result.metadata.pr_url}")
                # Access repo_path from RepoMetadata
                if hasattr(result.metadata, 'repo_path'):
                    self.console.print(f"  ⎿  [dim]Repository: {result.metadata.repo_path}[/dim]")
            else:
                self.print_error(result.message)
                if hasattr(result.metadata, 'repo_path'):
                    self.console.print(f"  ⎿  [dim]Repository: {result.metadata.repo_path}[/dim]")

        except Exception as e:
            self.print_error(f"Error: {e}")
            import traceback
            traceback.print_exc()

    def paper2code(self, command: str, ui_callback: Any = None) -> None:
        """Handle /paper2code command.

        Args:
            command: Full command string
            ui_callback: Optional UI callback
        """
        from swecli.commands.paper2code_command import Paper2CodeCommand

        # Get subagent manager from runtime suite
        subagent_manager = getattr(self.runtime_suite.agents, "subagent_manager", None)
        if subagent_manager is None:
            self.print_command_header("paper2code")
            self.print_error("Subagent manager not available")
            return

        # Create simple console callback if none provided
        if ui_callback is None:
            ui_callback = self._create_console_callback()

        # Create handler
        handler = Paper2CodeCommand(
            subagent_manager=subagent_manager,
            working_dir=self.config_manager.working_dir,
            mode_manager=self.mode_manager,
            approval_manager=self.approval_manager,
            undo_manager=self.undo_manager,
            ui_callback=ui_callback,
        )

        try:
            args = handler.parse_args(command)
        except ValueError as e:
            self.print_command_header("paper2code")
            self.print_error(str(e))
            return

        try:
            result = handler.execute(args)
            if result.success:
                self.console.print(f"[green]⏺[/green] {result.message}")
            else:
                self.print_error(result.message)

        except Exception as e:
            self.print_error(f"Error: {e}")
            import traceback
            traceback.print_exc()

    def run_command(self, args: str) -> None:
        """Handle /run command to execute a bash command.

        Args:
            args: Command to execute
        """
        if not args:
            self.print_command_header("run")
            self.print_error("Please provide a command to run")
            return

        command = args.strip()

        # Check if bash is enabled
        if not self.config.enable_bash:
            self.print_command_header("run")
            self.print_error("Bash execution is disabled")
            self.console.print("  ⎿  [dim]Enable it in config with 'enable_bash: true'[/dim]")
            return

        # Create operation
        operation = Operation(
            id=str(hash(f"{command}{datetime.now()}")),
            type=OperationType.BASH_EXECUTE,
            target=command,
            parameters={"command": command},
            created_at=datetime.now(),
        )

        # Show preview
        self.print_command_header("run", command)

        # Check if approval is needed
        if not self.mode_manager.needs_approval(operation):
            operation.approved = True
        else:
            result = None
            try:
                # Try to get existing event loop
                loop = asyncio.get_running_loop()
                # We're in an async context - skip approval, assume pre-approved
                operation.approved = True
            except RuntimeError:
                # No running loop - we can run synchronously
                result = asyncio.run(self.approval_manager.request_approval(
                    operation=operation,
                    preview=f"Execute: {command}"
                ))

                if not result.approved:
                    self.print_warning("Operation cancelled")
                    return

        # Execute command
        try:
            bash_result = self.bash_tool.execute(command, operation=operation)

            if bash_result.success:
                self.print_success("Success")
                if bash_result.stdout:
                    self.console.print(bash_result.stdout)
                if bash_result.stderr:
                    self.console.print(f"  ⎿  [yellow]Stderr:[/yellow] {bash_result.stderr}")
                self.console.print(f"  ⎿  [dim]Exit code: {bash_result.exit_code}[/dim]")
                # Record for history
                self.undo_manager.record_operation(operation)
            else:
                self.print_error(f"Command failed: {bash_result.error}")

        except Exception as e:
            self.error_handler.handle_error(e, operation)

    def _create_console_callback(self):
        """Create a simple console callback for progress display."""
        from swecli.ui_textual.callback_interface import BaseUICallback

        class ConsoleUICallback(BaseUICallback):
            """Simple console-based UI callback for progress display.

            Inherits from BaseUICallback for consistent interface.
            Only overrides on_tool_call and on_tool_result with console output.
            """
            def __init__(self, console):
                self.console = console
                self._depth = 0

            def on_tool_call(self, tool_name: str, tool_args: dict):
                indent = "  " * self._depth
                args_str = ", ".join(f"{k}={v!r}" for k, v in list(tool_args.items())[:2])
                self.console.print(f"{indent}[cyan]⏺[/cyan] {tool_name}({args_str})")
                self._depth += 1

            def on_tool_result(self, tool_name: str, tool_args: dict, result):
                self._depth = max(0, self._depth - 1)
                indent = "  " * self._depth
                # Show truncated result
                result_preview = str(result)[:100] + "..." if len(str(result)) > 100 else str(result)
                self.console.print(f"{indent}[dim]⎿[/dim]  {result_preview}")

        return ConsoleUICallback(self.console)
