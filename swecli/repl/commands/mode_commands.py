"""Mode commands for REPL."""

from typing import TYPE_CHECKING, Any

from rich.console import Console

from swecli.core.runtime import OperationMode
from swecli.repl.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from swecli.repl.repl import REPL


class ModeCommands(CommandHandler):
    """Handler for mode-related commands: /mode."""

    def __init__(
        self,
        console: Console,
        repl: "REPL",
    ):
        """Initialize mode commands handler.

        Args:
            console: Rich console for output
            repl: Reference to REPL for accessing current managers
        """
        super().__init__(console)
        self._repl = repl

    # Properties to access managers dynamically (avoids stale references)
    @property
    def mode_manager(self) -> Any:
        return self._repl.mode_manager

    @property
    def approval_manager(self) -> Any:
        return self._repl.approval_manager

    def handle(self, args: str) -> CommandResult:
        """Handle mode command (not used, individual methods called directly)."""
        raise NotImplementedError("Use specific method: switch_mode()")

    def switch_mode(self, mode_name: str) -> CommandResult:
        """Switch operation mode.

        Args:
            mode_name: Mode to switch to (normal/plan) or empty to show current

        Returns:
            CommandResult indicating success or failure
        """
        if not mode_name:
            # Show current mode - no header, just results
            self.print_result_only(f"Current: {self.mode_manager.current_mode.value.upper()}")
            self.print_result_only(self.mode_manager.get_mode_description())
            self.print_result_only("[dim]Available: normal, plan[/dim]")
            return CommandResult(success=True)

        mode_name = mode_name.strip().lower()

        try:
            if mode_name == "normal":
                new_mode = OperationMode.NORMAL
            elif mode_name == "plan":
                new_mode = OperationMode.PLAN
            else:
                self.print_error(f"Unknown mode: {mode_name}")
                self.print_result_only("[dim]Available: normal, plan[/dim]")
                return CommandResult(success=False, message=f"Unknown mode: {mode_name}")

            self.mode_manager.set_mode(new_mode)

            # Reset auto-approve when switching modes
            if hasattr(self.approval_manager, "reset_auto_approve"):
                self.approval_manager.reset_auto_approve()

            self.print_success(f"Switched to {new_mode.value.upper()} mode")
            self.print_result_only(self.mode_manager.get_mode_description())

            return CommandResult(
                success=True, message=f"Switched to {new_mode.value.upper()}", data=new_mode
            )

        except Exception as e:
            self.print_error(f"Error switching mode: {e}")
            return CommandResult(success=False, message=str(e))
