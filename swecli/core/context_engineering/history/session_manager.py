"""Session persistence and management."""

import json
from pathlib import Path
from typing import Optional, Union

from swecli.models.message import ChatMessage
from swecli.models.session import Session, SessionMetadata


class SessionManager:
    """Manages session persistence and retrieval.

    Sessions are stored in project-scoped directories under
    ``~/.swecli/projects/{encoded-path}/``.
    """

    def __init__(
        self,
        *,
        session_dir: Optional[Path] = None,
        working_dir: Optional[Path] = None,
    ):
        """Initialize session manager.

        Args:
            session_dir: Explicit directory override (tests, ``SWECLI_SESSION_DIR``).
            working_dir: Working directory used to compute the project-scoped
                session directory via :func:`paths.project_sessions_dir`.

        If neither argument is given, falls back to
        ``~/.swecli/projects/-unknown-/``.
        """
        if session_dir is not None:
            self.session_dir = Path(session_dir).expanduser()
        elif working_dir is not None:
            from swecli.core.paths import get_paths

            paths = get_paths()
            self.session_dir = paths.project_sessions_dir(working_dir)
        else:
            from swecli.core.paths import get_paths, FALLBACK_PROJECT_DIR_NAME

            paths = get_paths()
            self.session_dir = paths.global_projects_dir / FALLBACK_PROJECT_DIR_NAME

        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.current_session: Optional[Session] = None
        self.turn_count = 0

    def create_session(self, working_directory: Optional[str] = None) -> Session:
        """Create a new session.

        Args:
            working_directory: Working directory for the session

        Returns:
            New session instance
        """
        session = Session(working_directory=working_directory)
        self.current_session = session
        self.turn_count = 0
        return session

    @staticmethod
    def _load_from_file(path: Path) -> Session:
        """Load a session from a JSON file.

        Args:
            path: Path to the session JSON file.

        Returns:
            Loaded Session instance.

        Raises:
            FileNotFoundError: If the file doesn't exist.
        """
        if not path.exists():
            raise FileNotFoundError(f"Session file not found: {path}")

        with open(path) as f:
            data = json.load(f)

        return Session(**data)

    def load_session(self, session_id: str) -> Session:
        """Load a session from disk.

        Searches the local project directory first, then falls back to
        scanning all project directories (for ``--resume`` across projects).

        Args:
            session_id: Session ID to load

        Returns:
            Loaded session

        Raises:
            FileNotFoundError: If session file doesn't exist
        """
        # Try local project dir first
        session_file = self.session_dir / f"{session_id}.json"
        if session_file.exists():
            session = self._load_from_file(session_file)
            self.current_session = session
            self.turn_count = len(session.messages)
            return session

        # Fall back to searching all project directories
        from swecli.core.paths import get_paths

        paths = get_paths()
        projects_dir = paths.global_projects_dir
        if projects_dir.exists():
            for project_dir in projects_dir.iterdir():
                if not project_dir.is_dir():
                    continue
                candidate = project_dir / f"{session_id}.json"
                if candidate.exists():
                    session = self._load_from_file(candidate)
                    self.current_session = session
                    self.turn_count = len(session.messages)
                    return session

        raise FileNotFoundError(f"Session {session_id} not found")

    def save_session(self, session: Optional[Session] = None) -> None:
        """Save session to disk.

        Only saves sessions that have at least one message to avoid
        cluttering the session list with empty test sessions.

        Args:
            session: Session to save (defaults to current session)
        """
        session = session or self.current_session
        if not session:
            return

        # Only save sessions with at least one message
        if len(session.messages) == 0:
            return

        session_file = self.session_dir / f"{session.id}.json"

        with open(session_file, "w") as f:
            json.dump(session.model_dump(), f, indent=2, default=str)

    def add_message(self, message: ChatMessage, auto_save_interval: int = 5) -> None:
        """Add a message to the current session and auto-save if needed.

        Args:
            message: Message to add
            auto_save_interval: Save every N turns
        """
        if not self.current_session:
            raise ValueError("No active session")

        self.current_session.add_message(message)
        self.turn_count += 1

        # Auto-save
        if self.turn_count % auto_save_interval == 0:
            self.save_session()

    def list_sessions(self) -> list[SessionMetadata]:
        """List all saved sessions in this project directory.

        Returns:
            List of session metadata, sorted by update time (newest first)
            Filters out empty sessions (sessions with no messages)
        """
        sessions = []
        for session_file in self.session_dir.glob("*.json"):
            try:
                session = self._load_from_file(session_file)

                # Skip empty sessions (no messages)
                if len(session.messages) == 0:
                    # Optionally clean up empty session files
                    try:
                        session_file.unlink()
                    except Exception:
                        pass
                    continue

                sessions.append(session.get_metadata())
            except Exception:
                continue  # Skip corrupted files

        return sorted(sessions, key=lambda s: s.updated_at, reverse=True)

    def find_latest_session(
        self, working_directory: Union[Path, str, None] = None
    ) -> Optional[SessionMetadata]:
        """Find the most recently updated session.

        Since sessions are now project-scoped, this simply returns the newest
        session in the directory. The *working_directory* parameter is accepted
        for backward-compatibility but is no longer used for filtering.
        """
        sessions = self.list_sessions()
        return sessions[0] if sessions else None

    def load_latest_session(
        self, working_directory: Union[Path, str, None] = None
    ) -> Optional[Session]:
        """Load the most recent session."""
        metadata = self.find_latest_session(working_directory)
        if not metadata:
            return None
        return self.load_session(metadata.id)

    def delete_session(self, session_id: str) -> None:
        """Delete a session and its associated debug log.

        Args:
            session_id: Session ID to delete
        """
        session_file = self.session_dir / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()

        # Also remove the debug log if present
        debug_file = self.session_dir / f"{session_id}.debug"
        if debug_file.exists():
            debug_file.unlink()

    def get_current_session(self) -> Optional[Session]:
        """Get the current active session."""
        return self.current_session

    @staticmethod
    def generate_title(messages: list[dict]) -> str:
        """Generate a short title from the first user message.

        Simple heuristic: extract the first sentence, truncate to 50 chars.
        No LLM call required.

        Args:
            messages: List of message dicts with 'role' and 'content' keys

        Returns:
            A concise title string (max 50 chars)
        """
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "").strip()
                if not content:
                    continue
                # Take first sentence (or first line)
                for sep in (".", "\n", "?", "!"):
                    idx = content.find(sep)
                    if 0 < idx < 80:
                        content = content[:idx]
                        break
                title = content[:50].strip()
                return title if title else "Untitled"
        return "Untitled"

    def set_title(self, session_id: str, title: str) -> None:
        """Set the title for a session.

        Args:
            session_id: Session ID to update
            title: Title to set (max 50 chars)
        """
        title = title[:50]

        # Update in-memory if it's the current session
        if self.current_session and self.current_session.id == session_id:
            self.current_session.metadata["title"] = title
            self.save_session()
            return

        # Otherwise load, update, save
        session_file = self.session_dir / f"{session_id}.json"
        if not session_file.exists():
            return

        with open(session_file) as f:
            data = json.load(f)

        if "metadata" not in data:
            data["metadata"] = {}
        data["metadata"]["title"] = title

        with open(session_file, "w") as f:
            json.dump(data, f, indent=2, default=str)
