"""Centralized spinner service for all UI animations.

This module provides a unified SpinnerService that:
1. Provides facade API (start/update/stop) for ui_callback compatibility
2. Provides callback API (register) for widgets that manage their own spinners
3. Owns all timer lifecycle (Textual timer + threading.Timer fallback)
4. Invokes widget callbacks with SpinnerFrame data for rendering

The dual-timer pattern ensures animations work even when Textual's event loop
is blocked during synchronous LLM calls.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from rich.text import Text

from swecli.ui_textual.style_tokens import GREY

if TYPE_CHECKING:
    from textual.app import App
    from textual.timer import Timer
    from swecli.ui_textual.widgets.conversation_log import ConversationLog


class SpinnerType(Enum):
    """Types of spinners with different rendering behaviors."""

    TOOL = auto()      # Main tool spinner - braille dots, 120ms
    THINKING = auto()  # Thinking spinner - braille dots, 120ms, 300ms min visibility
    TODO = auto()      # Todo panel - rotating arrows, 150ms
    NESTED = auto()    # Nested/subagent tool - flashing bullet, 300ms


@dataclass(frozen=True)
class SpinnerConfig:
    """Immutable configuration for a spinner animation type."""

    chars: tuple[str, ...]
    interval_ms: int
    style: str
    min_visible_ms: int = 0


SPINNER_CONFIGS: Dict[SpinnerType, SpinnerConfig] = {
    SpinnerType.TOOL: SpinnerConfig(
        chars=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"),
        interval_ms=120,
        style="bright_cyan",
    ),
    SpinnerType.THINKING: SpinnerConfig(
        chars=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"),
        interval_ms=120,
        style="bright_cyan",
        min_visible_ms=300,
    ),
    SpinnerType.NESTED: SpinnerConfig(
        chars=("⏺", "○"),
        interval_ms=300,
        style="green",  # Flashing animation uses green (not cyan like spinners)
    ),
    SpinnerType.TODO: SpinnerConfig(
        chars=("←", "↖", "↑", "↗", "→", "↘", "↓", "↙"),
        interval_ms=150,
        style="yellow",
    ),
}


def get_spinner_config(spinner_type: SpinnerType) -> SpinnerConfig:
    """Get the configuration for a spinner type."""
    return SPINNER_CONFIGS.get(spinner_type, SPINNER_CONFIGS[SpinnerType.TOOL])


@dataclass
class SpinnerInstance:
    """State for a single active spinner."""

    spinner_id: str
    spinner_type: SpinnerType
    config: SpinnerConfig

    # Animation state
    frame_index: int = 0
    started_at: float = field(default_factory=time.monotonic)
    last_frame_at: float = field(default_factory=time.monotonic)

    # Content
    message: Text = field(default_factory=lambda: Text(""))
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Callback for rendering updates
    render_callback: Optional[Callable[["SpinnerFrame"], None]] = None

    # Stop handling
    stop_requested: bool = False
    stop_requested_at: float = 0.0


@dataclass
class SpinnerFrame:
    """Data passed to widget render callbacks each animation frame."""

    spinner_id: str
    spinner_type: SpinnerType
    char: str                    # Current animation character
    frame_index: int             # Current frame number
    elapsed_seconds: int         # Seconds since spinner started
    message: Text                # Current message text
    style: str                   # Style for the spinner character
    metadata: Dict[str, Any]     # Widget-specific data


class SpinnerService:
    """Centralized spinner management for all UI animations.

    This service provides TWO APIs:

    1. Facade API (for ui_callback compatibility):
       - start(message) -> spinner_id - Start spinner, delegates to ConversationLog
       - update(spinner_id, message) - Update spinner message
       - stop(spinner_id, success, message) - Stop spinner

    2. Callback API (for widgets that manage their own spinners):
       - register(type, callback) -> spinner_id - Register with animation callback
       - update_message(spinner_id, message) - Update message
       - stop(spinner_id, immediate) - Stop spinner

    Thread Safety:
    - All public methods are thread-safe
    - Internal state protected by RLock
    - UI updates dispatched via call_from_thread when needed

    Timer Architecture:
    - Single animation loop with GCD-based tick interval (60ms)
    - Each spinner tracks when its next frame is due
    - Dual-timer pattern: Textual timer (when loop is free) + threading.Timer (fallback)
    """

    # Tick interval - GCD of all spinner intervals for smooth animation
    _TICK_INTERVAL_MS = 60  # ~16fps base rate, divides evenly into 120, 300, 150

    def __init__(self, app: "App") -> None:
        """Initialize the SpinnerService.

        Args:
            app: The Textual App instance for timer scheduling
        """
        self.app = app
        self._lock = threading.RLock()

        # Active spinners by ID
        self._spinners: Dict[str, SpinnerInstance] = {}

        # Timer references
        self._textual_timer: Optional["Timer"] = None
        self._thread_timer: Optional[threading.Timer] = None

        # Animation loop state
        self._running = False

    @property
    def _conversation(self) -> Optional["ConversationLog"]:
        """Get the conversation log widget."""
        return getattr(self.app, "conversation", None)

    # =========================================================================
    # FACADE API (for ui_callback compatibility)
    # =========================================================================

    def start(
        self,
        message: str | Text,
        spinner_type: SpinnerType = SpinnerType.TOOL,
        min_visible_ms: int = 0,
    ) -> str:
        """Start a spinner and return its ID (FACADE API).

        This method delegates to ConversationLog methods to display the spinner.
        ConversationLog manages its own animation timer internally.

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

        # Delegate to ConversationLog (BLOCKING to ensure line is added)
        def _start_on_ui():
            if hasattr(conversation, "add_tool_call"):
                conversation.add_tool_call(display_text)
            if hasattr(conversation, "start_tool_execution"):
                conversation.start_tool_execution()

        self._run_blocking(_start_on_ui)
        return spinner_id

    def update(self, spinner_id: str, message: str | Text) -> None:
        """Update the spinner message in-place (FACADE API).

        Args:
            spinner_id: The spinner ID returned by start()
            message: New message to display
        """
        conversation = self._conversation
        if conversation is None:
            return

        # Convert to Text if string
        if isinstance(message, str):
            display_text = Text(message, style="white")
        else:
            display_text = message.copy()

        def _update_on_ui():
            if hasattr(conversation, "update_progress_text"):
                conversation.update_progress_text(display_text)

        self._run_non_blocking(_update_on_ui)

    def stop(
        self,
        spinner_id: str,
        success: bool = True,
        result_message: str = "",
    ) -> None:
        """Stop a spinner (FACADE API).

        Works for both facade and callback API spinners.

        Args:
            spinner_id: The spinner ID
            success: Whether the operation succeeded (affects bullet color)
            result_message: Optional message to display as the result
        """
        # First, try to stop as a callback-based spinner
        with self._lock:
            if spinner_id in self._spinners:
                del self._spinners[spinner_id]
                if not self._spinners:
                    self._stop_animation_loop()

        # Also delegate to ConversationLog for facade spinners
        conversation = self._conversation
        if conversation is None:
            return

        def _stop_on_ui():
            # Stop spinner (shows green/red bullet based on success)
            if hasattr(conversation, "stop_tool_execution"):
                conversation.stop_tool_execution(success)

            # Show result line if provided
            if result_message:
                result_line = Text("  ⎿  ", style=GREY)
                result_line.append(result_message, style=GREY)
                conversation.write(result_line)

        self._run_non_blocking(_stop_on_ui)

    # =========================================================================
    # CALLBACK API (for widgets that manage their own spinners)
    # =========================================================================

    def register(
        self,
        spinner_type: SpinnerType,
        render_callback: Callable[[SpinnerFrame], None],
        message: Optional[Text | str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a new spinner and return its ID (CALLBACK API).

        The spinner starts animating immediately. The render_callback will be
        invoked on each frame with SpinnerFrame data.

        Args:
            spinner_type: Type of spinner (determines chars, interval, style)
            render_callback: Called each frame with SpinnerFrame data
            message: Optional message to display with spinner
            metadata: Optional widget-specific data passed through to callback

        Returns:
            Unique spinner ID for later reference
        """
        spinner_id = str(uuid.uuid4())[:8]
        config = SPINNER_CONFIGS[spinner_type]

        # Convert message to Text if string
        if isinstance(message, str):
            msg_text = Text(message, style="white")
        elif message is not None:
            msg_text = message.copy()
        else:
            msg_text = Text("")

        instance = SpinnerInstance(
            spinner_id=spinner_id,
            spinner_type=spinner_type,
            config=config,
            message=msg_text,
            metadata=metadata or {},
            render_callback=render_callback,
        )

        with self._lock:
            self._spinners[spinner_id] = instance

            # Start animation loop if not running
            if not self._running:
                self._start_animation_loop()

        # Render initial frame immediately
        self._render_frame(instance)

        return spinner_id

    def update_message(self, spinner_id: str, message: Text | str) -> None:
        """Update the message for an active spinner (CALLBACK API).

        Args:
            spinner_id: ID returned by register()
            message: New message to display
        """
        with self._lock:
            instance = self._spinners.get(spinner_id)
            if instance is None:
                return

            if isinstance(message, str):
                instance.message = Text(message, style="white")
            else:
                instance.message = message.copy()

    def update_metadata(self, spinner_id: str, **kwargs: Any) -> None:
        """Update metadata fields for an active spinner (CALLBACK API).

        Args:
            spinner_id: ID returned by register()
            **kwargs: Key-value pairs to merge into metadata
        """
        with self._lock:
            instance = self._spinners.get(spinner_id)
            if instance is None:
                return
            instance.metadata.update(kwargs)

    def stop_all(self, immediate: bool = True) -> None:
        """Stop all active spinners.

        Args:
            immediate: If True, stop all immediately ignoring min visibility
        """
        with self._lock:
            self._spinners.clear()
            self._stop_animation_loop()

    def is_active(self, spinner_id: str) -> bool:
        """Check if a spinner is currently active."""
        with self._lock:
            return spinner_id in self._spinners

    def get_active_count(self) -> int:
        """Return count of active spinners."""
        with self._lock:
            return len(self._spinners)

    # =========================================================================
    # THREAD HELPERS
    # =========================================================================

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
                self.app.call_from_thread(func, *args, **kwargs)

    # =========================================================================
    # ANIMATION LOOP
    # =========================================================================

    def _start_animation_loop(self) -> None:
        """Start the animation loop (called with lock held)."""
        if self._running:
            return

        self._running = True
        self._schedule_tick()

    def _stop_animation_loop(self) -> None:
        """Stop the animation loop (called with lock held)."""
        self._running = False

        if self._textual_timer is not None:
            self._textual_timer.stop()
            self._textual_timer = None

        if self._thread_timer is not None:
            self._thread_timer.cancel()
            self._thread_timer = None

    def _schedule_tick(self) -> None:
        """Schedule next animation tick using dual-timer pattern."""
        if not self._running:
            return

        interval_sec = self._TICK_INTERVAL_MS / 1000

        # Cancel existing timers
        if self._textual_timer is not None:
            self._textual_timer.stop()
        if self._thread_timer is not None:
            self._thread_timer.cancel()
            self._thread_timer = None

        # Schedule Textual timer (works when event loop is free)
        self._textual_timer = self.app.set_timer(interval_sec, self._on_tick)

        # Schedule threading.Timer fallback (bypasses blocked event loop)
        self._thread_timer = threading.Timer(interval_sec, self._on_thread_tick)
        self._thread_timer.daemon = True
        self._thread_timer.start()

    def _on_thread_tick(self) -> None:
        """Fallback tick via threading.Timer when event loop is blocked."""
        if not self._running:
            return

        # Use call_from_thread to safely run on UI thread
        try:
            self.app.call_from_thread(self._on_tick)
        except Exception:
            pass  # App may be shutting down

    def _on_tick(self) -> None:
        """Animation tick - advance frames and render as needed."""
        # Cancel thread timer if this tick came from Textual timer
        if self._thread_timer is not None:
            self._thread_timer.cancel()
            self._thread_timer = None

        now = time.monotonic()

        with self._lock:
            if not self._running:
                return

            # Process each active spinner
            to_remove: list[str] = []
            to_render: list[SpinnerInstance] = []

            for spinner_id, instance in self._spinners.items():
                # Check for delayed stop
                if instance.stop_requested:
                    elapsed_ms = (now - instance.started_at) * 1000
                    if elapsed_ms >= instance.config.min_visible_ms:
                        to_remove.append(spinner_id)
                        continue

                # Check if this spinner is due for a frame update
                elapsed_since_frame = (now - instance.last_frame_at) * 1000
                if elapsed_since_frame >= instance.config.interval_ms:
                    # Advance frame
                    instance.frame_index = (
                        (instance.frame_index + 1) % len(instance.config.chars)
                    )
                    instance.last_frame_at = now

                    # Mark for rendering (outside lock)
                    to_render.append(instance)

            # Remove stopped spinners
            for spinner_id in to_remove:
                del self._spinners[spinner_id]

            # Stop loop if no spinners left
            if not self._spinners:
                self._stop_animation_loop()
                return

        # Render frames (outside lock to avoid deadlock)
        for instance in to_render:
            self._render_frame(instance)

        # Schedule next tick
        self._schedule_tick()

    def _render_frame(self, instance: SpinnerInstance) -> None:
        """Invoke the render callback for a spinner."""
        if instance.render_callback is None:
            return

        frame = SpinnerFrame(
            spinner_id=instance.spinner_id,
            spinner_type=instance.spinner_type,
            char=instance.config.chars[instance.frame_index],
            frame_index=instance.frame_index,
            elapsed_seconds=int(time.monotonic() - instance.started_at),
            message=instance.message.copy(),
            style=instance.config.style,
            metadata=instance.metadata.copy(),
        )

        try:
            instance.render_callback(frame)
        except Exception:
            pass  # Don't let callback errors crash the loop


__all__ = [
    "SpinnerService",
    "SpinnerType",
    "SpinnerConfig",
    "SpinnerFrame",
    "SpinnerInstance",
    "SPINNER_CONFIGS",
    "get_spinner_config",
]
