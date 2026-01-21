"""Session management commands for REPL."""

from typing import TYPE_CHECKING

from rich.console import Console

from swecli.repl.commands.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from swecli.core.runtime import ConfigManager
    from swecli.core.context_engineering.history import SessionManager


class SessionCommands(CommandHandler):
    """Handler for session-related commands: /clear."""

    def __init__(
        self,
        console: Console,
        session_manager: "SessionManager",
        config_manager: "ConfigManager",
    ):
        """Initialize session commands handler.

        Args:
            console: Rich console for output
            session_manager: Session manager instance
            config_manager: Configuration manager instance
        """
        super().__init__(console)
        self.session_manager = session_manager
        self.config_manager = config_manager

    def handle(self, args: str) -> CommandResult:
        """Handle session command (not used, individual methods called directly)."""
        raise NotImplementedError("Use specific method: clear()")

    def clear(self) -> CommandResult:
        """Clear current session and create a new one.

        Returns:
            CommandResult indicating success
        """
        if self.session_manager.current_session:
            self.session_manager.save_session()
            self.session_manager.create_session(
                working_directory=str(self.config_manager.working_dir)
            )
            self.print_success("Session cleared. Previous session saved.")
            self.console.print()
            return CommandResult(success=True, message="Session cleared")
        else:
            self.print_warning("No active session to clear.")
            self.console.print()
            return CommandResult(success=False, message="No active session")
