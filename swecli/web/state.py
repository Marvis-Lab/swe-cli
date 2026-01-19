"""Shared state manager for web UI and terminal REPL."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from threading import Lock

from swecli.core.runtime import ConfigManager, ModeManager
from swecli.core.context_engineering.history import SessionManager, UndoManager
from swecli.core.runtime.approval import ApprovalManager
from swecli.models.message import ChatMessage


# Type imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from swecli.core.context_engineering.mcp.manager import MCPManager


class WebState:
    """Shared state between CLI and web UI.

    This class maintains a single source of truth for:
    - Current session
    - Configuration
    - Message history
    - Agent state

    Thread-safe for concurrent access from REPL and web server.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        session_manager: SessionManager,
        mode_manager: ModeManager,
        approval_manager: ApprovalManager,
        undo_manager: UndoManager,
        mcp_manager: Optional["MCPManager"] = None,
    ):
        self.config_manager = config_manager
        self.session_manager = session_manager
        self.mode_manager = mode_manager
        self.approval_manager = approval_manager
        self.undo_manager = undo_manager
        self.mcp_manager = mcp_manager

        # Thread safety
        self._lock = Lock()

        # Connected WebSocket clients
        self._ws_clients: List[Any] = []

        # Pending approval requests
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}

        # Interrupt flag for stopping ongoing tasks
        self._interrupt_requested = False

    def add_ws_client(self, client: Any) -> None:
        """Add a WebSocket client."""
        with self._lock:
            if client not in self._ws_clients:
                self._ws_clients.append(client)

    def remove_ws_client(self, client: Any) -> None:
        """Remove a WebSocket client."""
        with self._lock:
            if client in self._ws_clients:
                self._ws_clients.remove(client)

    def get_ws_clients(self) -> List[Any]:
        """Get all connected WebSocket clients."""
        with self._lock:
            return self._ws_clients.copy()

    def get_messages(self) -> List[ChatMessage]:
        """Get current session messages."""
        session = self.session_manager.get_current_session()
        if session:
            return session.messages
        return []

    def add_message(self, message: ChatMessage) -> None:
        """Add a message to current session."""
        self.session_manager.add_message(message)

    def get_current_session_id(self) -> Optional[str]:
        """Get current session ID."""
        session = self.session_manager.get_current_session()
        return session.id if session else None

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all available sessions."""
        return [
            {
                "id": s.id,
                "working_dir": s.working_directory or "",
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
                "message_count": s.message_count,
                "total_tokens": s.total_tokens,
            }
            for s in self.session_manager.list_sessions()
        ]

    def resume_session(self, session_id: str) -> bool:
        """Resume a specific session."""
        try:
            self.session_manager.load_session(session_id)
            return True
        except Exception:
            return False

    def add_pending_approval(
        self,
        approval_id: str,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> None:
        """Add a pending approval request."""
        with self._lock:
            self._pending_approvals[approval_id] = {
                "tool_name": tool_name,
                "arguments": arguments,
                "resolved": False,
                "approved": None,
            }

    def resolve_approval(self, approval_id: str, approved: bool, auto_approve: bool = False) -> bool:
        """Resolve a pending approval request."""
        print(f"[State] resolve_approval called: id={approval_id}, approved={approved}")
        with self._lock:
            if approval_id in self._pending_approvals:
                print(f"[State] Found approval in pending list, marking as resolved")
                self._pending_approvals[approval_id]["resolved"] = True
                self._pending_approvals[approval_id]["approved"] = approved
                self._pending_approvals[approval_id]["auto_approve"] = auto_approve
                return True
            print(f"[State] Approval {approval_id} NOT FOUND in pending list!")
            print(f"[State] Current pending approvals: {list(self._pending_approvals.keys())}")
            return False

    def get_pending_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """Get a pending approval request."""
        with self._lock:
            return self._pending_approvals.get(approval_id)

    def clear_approval(self, approval_id: str) -> None:
        """Clear a resolved approval."""
        with self._lock:
            self._pending_approvals.pop(approval_id, None)

    def request_interrupt(self) -> None:
        """Request interruption of ongoing task."""
        with self._lock:
            self._interrupt_requested = True

    def clear_interrupt(self) -> None:
        """Clear the interrupt flag."""
        with self._lock:
            self._interrupt_requested = False

    def is_interrupt_requested(self) -> bool:
        """Check if interrupt has been requested."""
        with self._lock:
            return self._interrupt_requested


# Global state instance (will be initialized when web server starts)
_state: Optional[WebState] = None


def init_state(
    config_manager: ConfigManager,
    session_manager: SessionManager,
    mode_manager: ModeManager,
    approval_manager: ApprovalManager,
    undo_manager: UndoManager,
    mcp_manager: Optional["MCPManager"] = None,
) -> WebState:
    """Initialize the global state instance."""
    global _state
    _state = WebState(
        config_manager,
        session_manager,
        mode_manager,
        approval_manager,
        undo_manager,
        mcp_manager,
    )
    return _state


def get_state() -> WebState:
    """Get the global state instance."""
    if _state is None:
        # Auto-initialize with default managers for standalone server
        from pathlib import Path
        from swecli.core.runtime import ConfigManager, ModeManager
        from swecli.core.context_engineering.history import SessionManager, UndoManager
        from swecli.core.runtime.approval import ApprovalManager
        from swecli.core.context_engineering.mcp.manager import MCPManager
        from swecli.core.paths import get_paths
        from rich.console import Console

        console = Console()
        working_dir = Path.cwd()
        paths = get_paths(working_dir)

        config_manager = ConfigManager(working_dir)
        session_manager = SessionManager(paths.global_sessions_dir)
        mode_manager = ModeManager()
        approval_manager = ApprovalManager(console)
        undo_manager = UndoManager(50)

        # Initialize MCP manager
        mcp_manager = MCPManager(working_dir)

        # Don't create session on startup - let user create via UI

        return init_state(
            config_manager,
            session_manager,
            mode_manager,
            approval_manager,
            undo_manager,
            mcp_manager,
        )
    return _state


async def broadcast_to_all_clients(message: Dict[str, Any]) -> None:
    """Broadcast a message to all connected WebSocket clients.

    Args:
        message: Message to broadcast (will be JSON-serialized)
    """
    state = get_state()
    clients = state.get_ws_clients()

    import json

    for client in clients:
        try:
            await client.send_text(json.dumps(message))
        except Exception:
            # Client disconnected, will be cleaned up by WebSocket handler
            pass
