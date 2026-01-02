"""Unified spinner service for all UI operations."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

from rich.text import Text

if TYPE_CHECKING:  # pragma: no cover
    from swecli.ui_textual.chat_app import SWECLIChatApp
    from swecli.ui_textual.widgets.conversation_log import ConversationLog


class SpinnerType(Enum):
    """Types of spinners with different rendering behaviors."""

    TOOL = auto()      # Main tool spinner - braille dots
    PROGRESS = auto()  # Same as TOOL, alias for clarity
    NESTED = auto()    # Nested/subagent tool - flashing bullet
    TODO = auto()      # Todo panel - rotating arrows
    THINKING = auto()  # Thinking spinner - braille dots


@dataclass
class SpinnerConfig:
    """Configuration for a spinner animation."""

    chars: list[str]
    interval_ms: int
    style: str


# Centralized spinner configurations
SPINNER_CONFIGS: dict[SpinnerType, "SpinnerConfig"] = {
    SpinnerType.TOOL: SpinnerConfig(
        chars=["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        interval_ms=120,
        style="bright_cyan",
    ),
    SpinnerType.THINKING: SpinnerConfig(
        chars=["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        interval_ms=120,
        style="bright_cyan",
    ),
    SpinnerType.NESTED: SpinnerConfig(
        chars=["⏺", "○"],  # Flashing bullet: solid → empty
        interval_ms=300,   # Slower for visible flashing
        style="bright_cyan",
    ),
    SpinnerType.TODO: SpinnerConfig(
        chars=["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"],
        interval_ms=150,
        style="yellow",
    ),
}


def get_spinner_config(spinner_type: SpinnerType) -> SpinnerConfig:
    """Get the configuration for a spinner type."""
    return SPINNER_CONFIGS.get(spinner_type, SPINNER_CONFIGS[SpinnerType.TOOL])


@dataclass
class SpinnerState:
    """State for an active spinner."""

    spinner_id: str
    spinner_type: SpinnerType
    message: Text
    started_at: float = field(default_factory=time.monotonic)
    min_visible_ms: int = 0


class SpinnerService:
    """Unified spinner management for all UI operations.

    This service provides a single entry point for all spinner operations,
    handling thread safety automatically. All spinners go through this service
    to ensure consistent behavior.

    Thread Model:
    - start(): BLOCKING - uses call_from_thread to ensure timer is created
    - update(): NON-BLOCKING - uses call_soon_threadsafe for performance
    - stop(): NON-BLOCKING - schedules UI update without waiting

    Usage:
        spinner_service = app.spinner_service
        spinner_id = spinner_service.start("Loading...")
        # ... do work ...
        spinner_service.stop(spinner_id, success=True, result_message="Done!")
    """

    def __init__(self, app: "SWECLIChatApp") -> None:
        """Initialize the spinner service.

        Args:
            app: The Textual chat application instance
        """
        self.app = app
        self._active_spinners: dict[str, SpinnerState] = {}
        self._lock = threading.Lock()

    @property
    def _conversation(self) -> Optional["ConversationLog"]:
        """Get the conversation log widget."""
        return getattr(self.app, "conversation", None)

    def _is_ui_thread(self) -> bool:
        """Check if we're on the Textual UI thread."""
        loop = getattr(self.app, "_loop", None)
        if loop is None:
            return True  # Assume UI thread if no loop
        try:
            import asyncio

            running_loop = asyncio.get_running_loop()
            return running_loop is loop
        except RuntimeError:
            # No running loop means we're not in async context
            return False

    def _run_blocking(self, func, *args, **kwargs) -> None:
        """Run a function on the UI thread, blocking until complete."""
        if self._is_ui_thread():
            func(*args, **kwargs)
        else:
            self.app.call_from_thread(func, *args, **kwargs)

    def _run_non_blocking(self, func, *args, **kwargs) -> None:
        """Run a function on the UI thread without blocking."""
        if self._is_ui_thread():
            func(*args, **kwargs)
        else:
            loop = getattr(self.app, "_loop", None)
            if loop is not None:
                loop.call_soon_threadsafe(lambda: func(*args, **kwargs))
            else:
                # Fallback to blocking call if no loop available
                self.app.call_from_thread(func, *args, **kwargs)

    def start(
        self,
        message: str | Text,
        spinner_type: SpinnerType = SpinnerType.TOOL,
        min_visible_ms: int = 0,
    ) -> str:
        """Start a spinner and return its ID.

        This method is BLOCKING to ensure the spinner line is added before
        the operation starts. The actual paint visibility is ensured in stop().

        Args:
            message: The message to display with the spinner
            spinner_type: Type of spinner (TOOL or PROGRESS)
            min_visible_ms: Minimum time the spinner should be visible (in ms)

        Returns:
            A unique spinner ID for later reference
        """
        conversation = self._conversation
        if conversation is None:
            return ""

        # Convert to Text if string
        if isinstance(message, str):
            display_text = Text(message, style="white")
        else:
            display_text = message.copy()

        # Generate unique ID
        spinner_id = str(uuid.uuid4())[:8]

        # Create state
        state = SpinnerState(
            spinner_id=spinner_id,
            spinner_type=spinner_type,
            message=display_text,
            started_at=time.monotonic(),
            min_visible_ms=min_visible_ms,
        )

        with self._lock:
            self._active_spinners[spinner_id] = state

        # Start spinner on UI thread (BLOCKING to ensure line is added)
        def _start_on_ui():
            if hasattr(conversation, "add_tool_call"):
                conversation.add_tool_call(display_text)
            if hasattr(conversation, "start_tool_execution"):
                conversation.start_tool_execution()

        self._run_blocking(_start_on_ui)
        return spinner_id

    def update(self, spinner_id: str, message: str | Text) -> None:
        """Update the spinner message in-place.

        This method is NON-BLOCKING for performance. The spinner continues
        animating while the message is updated.

        Args:
            spinner_id: The spinner ID returned by start()
            message: New message to display
        """
        with self._lock:
            state = self._active_spinners.get(spinner_id)
            if state is None:
                return

            # Update stored message
            if isinstance(message, str):
                state.message = Text(message, style="white")
            else:
                state.message = message.copy()

        conversation = self._conversation
        if conversation is None:
            return

        def _update_on_ui():
            if hasattr(conversation, "update_progress_text"):
                conversation.update_progress_text(state.message)

        self._run_non_blocking(_update_on_ui)

    def stop(
        self,
        spinner_id: str,
        success: bool = True,
        result_message: str = "",
    ) -> None:
        """Stop a spinner and show the result.

        Args:
            spinner_id: The spinner ID returned by start()
            success: Whether the operation succeeded (affects bullet color)
            result_message: Optional message to display as the result
        """
        with self._lock:
            state = self._active_spinners.pop(spinner_id, None)

        if state is None:
            return

        conversation = self._conversation
        if conversation is None:
            return

        # Ensure at least one paint cycle has happened so spinner is visible
        # Textual's compositor typically runs at ~60fps (16ms per frame)
        # 50ms guarantees at least 2-3 paint cycles have occurred
        # This is only applied when operation completes very quickly
        elapsed_ms = (time.monotonic() - state.started_at) * 1000
        if elapsed_ms < 50:
            time.sleep((50 - elapsed_ms) / 1000)

        def _stop_on_ui():
            # Stop spinner (shows green/red bullet based on success)
            if hasattr(conversation, "stop_tool_execution"):
                conversation.stop_tool_execution(success)

            # Show result line if provided
            if result_message:
                result_line = Text("  ⎿  ", style="#a0a4ad")
                result_line.append(result_message, style="#a0a4ad")
                conversation.write(result_line)

        self._run_non_blocking(_stop_on_ui)

    def is_active(self, spinner_id: str) -> bool:
        """Check if a spinner is currently active.

        Args:
            spinner_id: The spinner ID to check

        Returns:
            True if the spinner is active, False otherwise
        """
        with self._lock:
            return spinner_id in self._active_spinners

    def stop_all(self, success: bool = False) -> None:
        """Stop all active spinners.

        Useful for cleanup during interrupts or errors.

        Args:
            success: Whether to show success (green) or failure (red) bullets
        """
        with self._lock:
            spinner_ids = list(self._active_spinners.keys())

        for spinner_id in spinner_ids:
            self.stop(spinner_id, success=success)


__all__ = ["SpinnerService", "SpinnerType", "SpinnerState"]
