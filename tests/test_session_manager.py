"""Tests for session manager convenience helpers."""

from pathlib import Path

from swecli.core.context_engineering.history.session_manager import SessionManager
from swecli.models.message import ChatMessage, Role


def test_find_latest_session(tmp_path):
    session_dir = tmp_path / "sessions"
    manager = SessionManager(session_dir)

    repo = tmp_path / "repo"

    manager.create_session(str(repo))
    manager.add_message(ChatMessage(role=Role.USER, content="first"))
    manager.save_session()

    # Create a second, more recent session for the same repo
    second = manager.create_session(str(repo))
    manager.add_message(ChatMessage(role=Role.USER, content="hello"))
    manager.save_session()

    latest = manager.find_latest_session(repo)
    assert latest is not None
    assert latest.id == second.id

    # Ensure non-matching directory returns None
    assert manager.find_latest_session(tmp_path / "other") is None


def test_load_latest_session(tmp_path):
    session_dir = tmp_path / "sessions"
    manager = SessionManager(session_dir)

    repo = tmp_path / "repo"
    other = tmp_path / "other"

    manager.create_session(str(repo))
    manager.add_message(ChatMessage(role=Role.USER, content="repo"))
    manager.save_session()

    manager.create_session(str(other))
    manager.add_message(ChatMessage(role=Role.USER, content="other"))
    manager.save_session()

    session = manager.load_latest_session(other)
    assert session is not None
    assert Path(session.working_directory).resolve() == other.resolve()
