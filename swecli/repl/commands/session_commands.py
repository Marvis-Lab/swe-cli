"""Session management commands for REPL."""

from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from swecli.repl.commands.base import CommandHandler, CommandResult
from swecli.ui_textual.style_tokens import CYAN, SUBTLE, GREEN_BRIGHT, ERROR

if TYPE_CHECKING:
    from swecli.core.runtime import ConfigManager
    from swecli.core.context_engineering.history import SessionManager


class SessionCommands(CommandHandler):
    """Handler for session-related commands: /clear, /sessions, /resume."""

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
        raise NotImplementedError("Use specific methods: clear(), list_sessions(), resume()")

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
            return CommandResult(success=True, message="Session cleared")
        else:
            self.print_warning("No active session to clear.")
            return CommandResult(success=False, message="No active session")

    def list_sessions(self) -> CommandResult:
        """List all saved sessions.

        Returns:
            CommandResult with list of sessions
        """
        sessions = self.session_manager.list_sessions()

        if not sessions:
            self.print_warning("No saved sessions found.")
            return CommandResult(success=True, message="No sessions found")

        self.console.print("\n[bold]Saved Sessions:[/bold]\n")
        for session in sessions:
            self.console.print(
                f"  [{CYAN}]{session.id}[/{CYAN}] - "
                f"{session.updated_at.strftime('%Y-%m-%d %H:%M')} - "
                f"{session.message_count} messages - "
                f"{session.total_tokens} tokens"
            )
        self.console.print()

        return CommandResult(success=True, data=sessions)

    def resume(self, session_id: Optional[str]) -> CommandResult:
        """Resume a previous session."""
        candidate = (session_id or "").strip()

        if not candidate:
            latest = self.session_manager.find_latest_session(self.config_manager.working_dir)
            if not latest:
                self.print_warning("No saved sessions for this repository.")
                return CommandResult(success=False, message="No sessions available")
            candidate = latest.id
            self.print_success(f"Resuming latest session {candidate}")

        try:
            session = self.session_manager.load_session(candidate)
            if session.working_directory:
                self.config_manager.working_dir = Path(session.working_directory)
            return CommandResult(success=True, message=f"Resumed {candidate}")
        except FileNotFoundError:
            self.print_error(f"Session {candidate} not found.")
            return CommandResult(success=False, message=f"Session {candidate} not found")

    def changed_files(self) -> CommandResult:
        """Display all file changes made in the current session.

        Returns:
            CommandResult with file changes data
        """
        session = self.session_manager.get_current_session()

        if not session:
            self.print_warning("No active session.")
            return CommandResult(success=False, message="No active session")

        if not session.file_changes:
            self.console.print(f"\n[{SUBTLE}]No file changes recorded in this session yet.[/{SUBTLE}]\n")
            return CommandResult(success=True, message="No file changes")

        # Get summary
        summary = session.get_file_changes_summary()

        # Render summary and table
        files_label = "file" if summary["total"] == 1 else "files"
        summary_panel = Panel.fit(
            f"[bold]{summary['total']} {files_label} changed[/bold]\n"
            f"[green]+{summary['total_lines_added']}[/green] "
            f"[red]-{summary['total_lines_removed']}[/red] "
            f"[cyan]net {summary['net_lines']:+d}[/cyan]",
            title="File Changes",
            subtitle="Current session",
            border_style=CYAN,
            padding=(1, 3),
        )

        self.console.print()
        self.console.print(summary_panel)
        self.console.print()

        table = Table(
            box=box.MINIMAL_DOUBLE_HEAD,
            header_style=f"bold {CYAN}",
            expand=True,
            show_lines=False,
        )
        table.add_column("File", style="bold", no_wrap=True)
        table.add_column("Details", overflow="fold")
        table.add_column("Δ Lines", justify="right", no_wrap=True)
        table.add_column("When", style=SUBTLE, no_wrap=True)

        now = datetime.now()

        def format_time_ago(ts: datetime) -> str:
            diff = now - ts
            seconds = int(diff.total_seconds())
            if seconds < 60:
                return "just now"
            if seconds < 3600:
                return f"{seconds // 60}m ago"
            if diff.days == 0:
                return f"{seconds // 3600}h ago"
            return f"{diff.days}d ago"

        def format_delta(lines_added: int, lines_removed: int) -> str:
            parts = []
            if lines_added:
                parts.append(f"[{GREEN_BRIGHT}]+{lines_added}[/{GREEN_BRIGHT}]")
            if lines_removed:
                parts.append(f"[{ERROR}]-{lines_removed}[/{ERROR}]")
            return " ".join(parts) if parts else f"[{SUBTLE}]—[/{SUBTLE}]"

        for change in sorted(session.file_changes, key=lambda c: c.timestamp, reverse=True):
            icon = change.get_file_icon()
            color = change.get_status_color()
            file_name = Path(change.file_path).name if change.file_path else "—"
            time_ago = format_time_ago(change.timestamp)
            delta_text = format_delta(change.lines_added, change.lines_removed)

            descriptor = change.description or change.get_change_summary()
            details = f"[{color}]{change.type.value.title()}[/{color}] · {descriptor}"
            if change.file_path:
                details += f"\n[{SUBTLE}]{change.file_path}[/{SUBTLE}]"

            table.add_row(
                f"{icon} {file_name}",
                details,
                delta_text,
                time_ago,
            )

        self.console.print(table)
        self.console.print()

        return CommandResult(success=True, data=summary)
