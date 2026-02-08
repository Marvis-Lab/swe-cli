"""Session persistence and management."""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from swecli.models.message import ChatMessage
from swecli.models.session import Session, SessionMetadata

_INDEX_VERSION = 1


class SessionManager:
    """Manages session persistence and retrieval.

    Sessions are stored in project-scoped directories under
    ``~/.swecli/projects/{encoded-path}/``.

    A lightweight ``sessions-index.json`` file caches session metadata so that
    ``list_sessions()`` is O(1) reads instead of O(N) full-file parses. The
    index is self-healing: if it is missing or corrupted, it is transparently
    rebuilt from the individual session ``.json`` files.
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

    # ========================================================================
    # Index helpers
    # ========================================================================

    @property
    def _index_path(self) -> Path:
        """Path to the sessions index file."""
        from swecli.core.paths import SESSIONS_INDEX_FILE_NAME

        return self.session_dir / SESSIONS_INDEX_FILE_NAME

    def _read_index(self) -> Optional[dict]:
        """Read the sessions index file.

        Returns:
            Parsed index dict if valid, ``None`` if missing/corrupted/wrong version.
        """
        try:
            if not self._index_path.exists():
                return None
            with open(self._index_path) as f:
                data = json.load(f)
            if not isinstance(data, dict) or data.get("version") != _INDEX_VERSION:
                return None
            if not isinstance(data.get("entries"), list):
                return None
            return data
        except (json.JSONDecodeError, OSError):
            return None

    def _write_index(self, entries: list[dict]) -> None:
        """Atomically write the sessions index file.

        Writes to a temporary file first, then renames to prevent torn reads.
        """
        data = {"version": _INDEX_VERSION, "entries": entries}
        # Write to temp file in the same directory, then rename (atomic on POSIX)
        fd, tmp_path = tempfile.mkstemp(
            dir=self.session_dir, suffix=".tmp", prefix=".sessions-index-"
        )
        try:
            with open(fd, "w") as f:
                json.dump(data, f, indent=2, default=str)
            Path(tmp_path).replace(self._index_path)
        except Exception:
            # Clean up temp file on failure
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
            raise

    @staticmethod
    def _session_to_index_entry(session: Session) -> dict:
        """Convert a Session to a camelCase index entry dict."""
        return {
            "sessionId": session.id,
            "created": session.created_at.isoformat(),
            "modified": session.updated_at.isoformat(),
            "messageCount": len(session.messages),
            "totalTokens": session.total_tokens(),
            "title": session.metadata.get("title"),
            "summary": session.metadata.get("summary"),
            "tags": session.metadata.get("tags", []),
            "workingDirectory": session.working_directory,
        }

    @staticmethod
    def _metadata_from_index_entry(entry: dict) -> SessionMetadata:
        """Convert a camelCase index entry dict to a SessionMetadata."""
        return SessionMetadata(
            id=entry["sessionId"],
            created_at=datetime.fromisoformat(entry["created"]),
            updated_at=datetime.fromisoformat(entry["modified"]),
            message_count=entry.get("messageCount", 0),
            total_tokens=entry.get("totalTokens", 0),
            title=entry.get("title"),
            summary=entry.get("summary"),
            tags=entry.get("tags", []),
            working_directory=entry.get("workingDirectory"),
        )

    def _update_index_entry(self, session: Session) -> None:
        """Upsert a single session entry in the index."""
        index = self._read_index()
        if index is None:
            # Index missing/corrupted — rebuild it entirely
            self.rebuild_index()
            index = self._read_index()
            if index is None:
                return  # Rebuild itself failed — nothing we can do

        new_entry = self._session_to_index_entry(session)
        entries = index["entries"]

        # Replace existing entry or append
        for i, entry in enumerate(entries):
            if entry.get("sessionId") == session.id:
                entries[i] = new_entry
                self._write_index(entries)
                return

        entries.append(new_entry)
        self._write_index(entries)

    def _remove_index_entry(self, session_id: str) -> None:
        """Remove a single session entry from the index."""
        index = self._read_index()
        if index is None:
            return  # Nothing to remove from

        entries = [e for e in index["entries"] if e.get("sessionId") != session_id]
        self._write_index(entries)

    def rebuild_index(self) -> list[SessionMetadata]:
        """Rebuild the index from individual session ``.json`` files.

        This is the self-healing path: called when the index is missing or
        corrupted. It globs all ``.json`` files (excluding the index itself),
        loads each session, and recreates the index.

        Returns:
            List of ``SessionMetadata`` for all valid, non-empty sessions.
        """
        from swecli.core.paths import SESSIONS_INDEX_FILE_NAME

        entries: list[dict] = []
        metadata_list: list[SessionMetadata] = []

        for session_file in self.session_dir.glob("*.json"):
            # Skip the index file itself
            if session_file.name == SESSIONS_INDEX_FILE_NAME:
                continue

            try:
                session = self._load_from_file(session_file)

                # Skip empty sessions
                if len(session.messages) == 0:
                    try:
                        session_file.unlink()
                    except Exception:
                        pass
                    continue

                entry = self._session_to_index_entry(session)
                entries.append(entry)
                metadata_list.append(self._metadata_from_index_entry(entry))
            except Exception:
                continue  # Skip corrupted files

        self._write_index(entries)
        return sorted(metadata_list, key=lambda s: s.updated_at, reverse=True)

    # ========================================================================
    # Core session operations
    # ========================================================================

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

        After writing the session file, auto-generates a title (if not already
        set) and updates the sessions index.

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

        # Auto-generate title before writing (single write)
        if not session.metadata.get("title"):
            msg_dicts = [
                {"role": m.role.value, "content": m.content} for m in session.messages
            ]
            title = self.generate_title(msg_dicts)
            if title != "Untitled":
                session.metadata["title"] = title

        with open(session_file, "w") as f:
            json.dump(session.model_dump(), f, indent=2, default=str)

        # Update the sessions index
        self._update_index_entry(session)

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

        Reads from the sessions index for O(1) performance. Falls back to
        a full rebuild if the index is missing or corrupted.

        Returns:
            List of session metadata, sorted by update time (newest first)
        """
        index = self._read_index()
        if index is not None:
            sessions = [self._metadata_from_index_entry(e) for e in index["entries"]]
            return sorted(sessions, key=lambda s: s.updated_at, reverse=True)

        # Index missing or corrupted — rebuild (returns sorted)
        return self.rebuild_index()

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

        Also removes the session from the sessions index.

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

        # Remove from sessions index
        self._remove_index_entry(session_id)

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

        # Otherwise load, update, save on disk
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

        # Update the index for the on-disk-only path
        try:
            session = self._load_from_file(session_file)
            self._update_index_entry(session)
        except Exception:
            pass
