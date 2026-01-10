"""Tests for REPL session command helpers."""


from rich.console import Console

from swecli.core.runtime import ConfigManager, SessionManager
from swecli.models.message import ChatMessage, Role
from swecli.repl.commands.session_commands import SessionCommands


def _make_console():
    return Console(record=True)


def test_resume_latest_session(tmp_path):
    console = _make_console()
    session_dir = tmp_path / "sessions"
    manager = SessionManager(session_dir)

    config_manager = ConfigManager(tmp_path)

    # First session
    manager.create_session(str(tmp_path))
    manager.add_message(ChatMessage(role=Role.USER, content="first"))
    manager.save_session()

    # Second (latest) session
    latest = manager.create_session(str(tmp_path))
    manager.add_message(ChatMessage(role=Role.USER, content="second"))
    manager.save_session()

    commands = SessionCommands(console, manager, config_manager)
    result = commands.resume("")

    assert result.success
    assert manager.current_session.id == latest.id


def test_resume_latest_no_sessions(tmp_path):
    console = _make_console()
    manager = SessionManager(tmp_path / "sessions")
    config_manager = ConfigManager(tmp_path)

    commands = SessionCommands(console, manager, config_manager)
    result = commands.resume("")

    assert not result.success
    assert manager.current_session is None
