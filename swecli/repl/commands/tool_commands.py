"""Command handlers for tool-related commands (/init)."""

from pathlib import Path
from typing import Any

from rich.console import Console

from swecli.core.runtime.approval import ApprovalManager
from swecli.core.runtime import ModeManager
from swecli.core.context_engineering.history import SessionManager, UndoManager
from swecli.core.agents.prompts import load_prompt
from swecli.core.agents.subagents.manager import SubAgentDeps
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
        """Initialize tool commands handler."""
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
        """Handle /init command to analyze codebase and generate OPENDEV.md.

        Uses Code-Explorer subagent to thoroughly explore the codebase and
        generate a comprehensive OPENDEV.md file.

        Args:
            command: The full command string (e.g., "/init" or "/init /path/to/project")
        """
        # Parse path from command
        parts = command.strip().split()
        if len(parts) > 1:
            target_path = Path(parts[1]).expanduser().absolute()
        else:
            target_path = Path.cwd()

        # Validate path
        if not target_path.exists():
            self.print_command_header("init")
            self.print_error(f"Path does not exist: {target_path}")
            return

        if not target_path.is_dir():
            self.print_command_header("init")
            self.print_error(f"Path is not a directory: {target_path}")
            return

        self.print_command_header("init")
        self.console.print(f"[cyan]Analyzing codebase at {target_path}...[/cyan]")

        # Load the init system prompt and substitute path
        try:
            task_prompt = load_prompt("init_system_prompt")
            task_prompt = task_prompt.replace("{path}", str(target_path))
        except Exception as e:
            self.print_error(f"Failed to load init prompt: {e}")
            return

        # Get subagent manager from runtime suite's agents
        subagent_manager = getattr(
            getattr(self.runtime_suite, "agents", None), "subagent_manager", None
        )
        if subagent_manager is None:
            self.print_error("Subagent manager not available")
            return

        # Create dependencies for subagent execution
        deps = SubAgentDeps(
            mode_manager=self.mode_manager,
            approval_manager=self.approval_manager,
            undo_manager=self.undo_manager,
        )

        # Execute Init subagent with the init task
        try:
            result = subagent_manager.execute_subagent(
                name="Init",
                task=task_prompt,
                deps=deps,
                ui_callback=None,  # No UI callback for CLI mode
                working_dir=str(target_path),
            )

            if result.get("success"):
                opendev_path = target_path / "OPENDEV.md"
                if opendev_path.exists():
                    self.print_success(f"Generated OPENDEV.md at {opendev_path}")
                else:
                    self.print_success("Analysis complete")
                    if "content" in result:
                        self.console.print(f"[dim]{result['content'][:500]}...[/dim]")
            else:
                self.print_error(result.get("error", "Unknown error"))

        except Exception as e:
            self.print_error(f"Error during initialization: {e}")
            import traceback
            traceback.print_exc()
