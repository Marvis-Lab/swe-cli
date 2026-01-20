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

from swecli.ui_textual.style_tokens import GREY, PRIMARY, GREEN_BRIGHT, BLUE_BRIGHT, ERROR, WARNING

if TYPE_CHECKING:
    from textual.app import App
    from textual.timer import Timer
    from swecli.ui_textual.widgets.conversation_log import ConversationLog
    from swecli.ui_textual.components import TipsManager


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
        style=BLUE_BRIGHT,
    ),
    SpinnerType.THINKING: SpinnerConfig(
        chars=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"),
        interval_ms=120,
        style=BLUE_BRIGHT,
        min_visible_ms=300,
    ),
    SpinnerType.NESTED: SpinnerConfig(
        chars=("⏺", "○"),
        interval_ms=300,
        style=GREEN_BRIGHT,  # Flashing animation uses green (not cyan like spinners)
    ),
    SpinnerType.TODO: SpinnerConfig(
        chars=("←", "↖", "↑", "↗", "→", "↘", "↓", "↙"),
        interval_ms=150,
        style=WARNING,
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

        # Per-spinner line tracking for parallel tool execution
        # Maps spinner_id -> line number where spinner was written
        self._spinner_lines: Dict[str, int] = {}
        # Maps spinner_id -> display text for rebuilding final line
        self._spinner_displays: Dict[str, Text] = {}
        # Maps spinner_id -> line number where result placeholder was written
        self._result_lines: Dict[str, int] = {}
        # Maps spinner_id -> line number where spacing placeholder was written
        self._spacing_lines: Dict[str, int] = {}
        # Maps spinner_id -> tip text for this spinner
        self._spinner_tips: Dict[str, str] = {}
        # Maps spinner_id -> line number where tip was written
        self._spinner_tip_lines: Dict[str, int] = {}
        # TipsManager for rotating tips below spinners
        self._tips_manager: Optional["TipsManager"] = None

    @property
    def _conversation(self) -> Optional["ConversationLog"]:
        """Get the conversation log widget."""
        return getattr(self.app, "conversation", None)

    def set_tips_manager(self, tips_manager: "TipsManager") -> None:
        """Set the TipsManager for tip display below spinners.

        Args:
            tips_manager: TipsManager instance for rotating tips
        """
        self._tips_manager = tips_manager

    # =========================================================================
    # FACADE API (for ui_callback compatibility)
    # =========================================================================

    def start(
        self,
        message: str | Text,
        spinner_type: SpinnerType = SpinnerType.TOOL,
        min_visible_ms: int = 0,
        skip_placeholder: bool = False,
    ) -> str:
        """Start a spinner and return its ID (FACADE API).

        This method tracks line numbers per spinner_id to support parallel
        tool execution. Each spinner gets its own line that can be updated
        independently when stop() is called.

        Args:
            message: The message to display with the spinner
            spinner_type: Type of spinner (TOOL or PROGRESS)
            min_visible_ms: Minimum time the spinner should be visible (in ms)
            skip_placeholder: If True, don't write placeholders (for bash commands)

        Returns:
            A unique spinner ID for later reference
        """
        conversation = self._conversation
        if conversation is None:
            return ""

        # Convert to Text if string
        if isinstance(message, str):
            display_text = Text(message, style=PRIMARY)
        else:
            display_text = message.copy()

        # Generate unique ID
        spinner_id = str(uuid.uuid4())[:8]

        # Store display text for later use in stop()
        self._spinner_displays[spinner_id] = display_text.copy()

        # Delegate to ConversationLog (BLOCKING to ensure line is added)
        # Track line number for this specific spinner
        def _start_on_ui():
            # Add blank line for spacing if there are other active spinners
            if self._spinner_lines:
                conversation.write(Text(""))

            if hasattr(conversation, "add_tool_call"):
                conversation.add_tool_call(display_text)
            # DON'T call start_tool_execution() - we manage animation ourselves
            # This prevents DefaultToolRenderer from overwriting parallel spinners

            # Get line number from tool_renderer's _tool_call_start
            # This is more reliable because RichLog.write() is async and len(lines)
            # might not update immediately. _tool_call_start is set BEFORE the async write.
            if hasattr(conversation, "_tool_renderer") and hasattr(conversation._tool_renderer, "_tool_call_start"):
                line_num = conversation._tool_renderer._tool_call_start
            else:
                # Fallback: get the last line index
                line_num = len(conversation.lines) - 1

            # Store line number for this spinner
            self._spinner_lines[spinner_id] = line_num

            # Write tip line below spinner if TipsManager is available
            if self._tips_manager:
                tip = self._tips_manager.get_next_tip()
                if tip:
                    tip_line_num = len(conversation.lines)
                    tip_text = Text()
                    tip_text.append("  ⎿  Tip: ", style=GREY)
                    tip_text.append(tip, style=GREY)
                    conversation.write(tip_text)
                    self._spinner_tips[spinner_id] = tip
                    self._spinner_tip_lines[spinner_id] = tip_line_num

            # Write placeholders only for non-bash tools
            # Bash commands don't need placeholders - their output is rendered separately
            if not skip_placeholder:
                # Write TWO placeholders:
                # 1. Result placeholder - updated with result in stop()
                # 2. Spacing placeholder - stays as blank line between tool blocks
                result_line_num = len(conversation.lines)
                conversation.write(Text(""))  # Result placeholder
                self._result_lines[spinner_id] = result_line_num

                spacing_line_num = len(conversation.lines)
                conversation.write(Text(""))  # Spacing placeholder
                self._spacing_lines[spinner_id] = spacing_line_num

        self._run_blocking(_start_on_ui)

        # Register with animation loop via Callback API
        # This allows each spinner to animate its own line independently
        def render_callback(frame: SpinnerFrame) -> None:
            self._render_facade_spinner(spinner_id, frame)

        config = SPINNER_CONFIGS[spinner_type]
        instance = SpinnerInstance(
            spinner_id=spinner_id,
            spinner_type=spinner_type,
            config=config,
            message=display_text.copy() if isinstance(display_text, Text) else Text(str(display_text)),
            render_callback=render_callback,
        )

        should_start_loop = False
        with self._lock:
            self._spinners[spinner_id] = instance
            if not self._running:
                should_start_loop = True

        # Start animation loop AFTER releasing lock to avoid deadlock
        # (_on_tick tries to acquire the same lock)
        if should_start_loop:
            self._start_animation_loop()

        # Render initial frame immediately and BLOCK until it's displayed
        # This ensures the user sees the spinner character right away, not the static bullet
        self._render_initial_frame_blocking(spinner_id, display_text)

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
            display_text = Text(message, style=PRIMARY)
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

        Uses stored line number to update the correct line for this specific
        spinner, enabling parallel tool execution where multiple spinners
        can be stopped independently in any order.

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

        # Get stored line numbers and display for this spinner
        line_num = self._spinner_lines.pop(spinner_id, None)
        display_text = self._spinner_displays.pop(spinner_id, None)
        result_line_num = self._result_lines.pop(spinner_id, None)
        spacing_line_num = self._spacing_lines.pop(spinner_id, None)
        # Get tip line number BEFORE popping (needed for deletion in _stop_on_ui)
        tip_line_num = self._spinner_tip_lines.pop(spinner_id, None)
        self._spinner_tips.pop(spinner_id, None)

        conversation = self._conversation
        if conversation is None:
            return

        def _stop_on_ui():
            nonlocal result_line_num, spacing_line_num

            # Call stop_tool_execution for animation timer cleanup
            if hasattr(conversation, "stop_tool_execution"):
                conversation.stop_tool_execution(success)

            # Convert Text to Strip helper
            def text_to_strip(text: Text) -> "Strip":
                from rich.console import Console
                from textual.strip import Strip
                console = Console(width=1000, force_terminal=True, no_color=False)
                segments = list(text.render(console))
                return Strip(segments)

            # If we have a stored line number, directly update that specific line
            # This ensures parallel tools update their own lines correctly
            if line_num is not None and display_text is not None:
                if line_num < len(conversation.lines):
                    # Build the final line with success/failure bullet
                    # No leading spaces - matches tool_renderer.py format
                    # Green only for bullet, text preserves its own style (PRIMARY)
                    bullet_style = GREEN_BRIGHT if success else ERROR
                    final_line = Text()
                    final_line.append("⏺ ", style=bullet_style)
                    final_line.append_text(display_text)  # Preserves display_text's PRIMARY style

                    # Directly update the line at stored position
                    conversation.lines[line_num] = text_to_strip(final_line)

            # Delete tip line if it exists (inserted after spinner, before placeholders)
            if tip_line_num is not None and tip_line_num < len(conversation.lines):
                del conversation.lines[tip_line_num]
                # Adjust indices for lines that came after the deleted tip line
                if result_line_num is not None:
                    result_line_num -= 1
                if spacing_line_num is not None:
                    spacing_line_num -= 1

            # Update result placeholder if it exists (non-bash tools only)
            # Bash commands don't have placeholders - they render output separately
            if result_line_num is not None and result_line_num < len(conversation.lines):
                if result_message:
                    result_line = Text("  ⎿  ", style=GREY)
                    result_line.append(result_message, style=GREY)
                    conversation.lines[result_line_num] = text_to_strip(result_line)

            # Store spacing line number for add_tool_result_continuation to use
            # It will overwrite this line with the first diff line (no gap)
            conversation._pending_spacing_line = spacing_line_num

            conversation.refresh()

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
            msg_text = Text(message, style=PRIMARY)
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

        should_start_loop = False
        with self._lock:
            self._spinners[spinner_id] = instance
            if not self._running:
                should_start_loop = True

        # Start animation loop AFTER releasing lock to avoid deadlock
        if should_start_loop:
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
                instance.message = Text(message, style=PRIMARY)
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

    def clear_all_tips(self) -> None:
        """Clear all tip lines from active spinners.

        This is called when the approval modal appears to prevent tips
        from being displayed alongside the approval prompt.
        """
        conversation = self._conversation
        if conversation is None:
            return

        def _clear_on_ui():
            # Build list of (spinner_id, tip_line_num) sorted by line number descending
            # so we can delete from bottom to top without index shifting issues
            tips_to_delete = []
            for spinner_id, tip_line_num in list(self._spinner_tip_lines.items()):
                if tip_line_num < len(conversation.lines):
                    tips_to_delete.append((spinner_id, tip_line_num))

            # Sort by line number descending
            tips_to_delete.sort(key=lambda x: x[1], reverse=True)

            # Delete each tip line and adjust result/spacing lines
            for spinner_id, tip_line_num in tips_to_delete:
                del conversation.lines[tip_line_num]

                # Adjust result and spacing line indices for this spinner
                if spinner_id in self._result_lines:
                    if self._result_lines[spinner_id] > tip_line_num:
                        self._result_lines[spinner_id] -= 1
                if spinner_id in self._spacing_lines:
                    if self._spacing_lines[spinner_id] > tip_line_num:
                        self._spacing_lines[spinner_id] -= 1

            # Clear tip tracking
            self._spinner_tips.clear()
            self._spinner_tip_lines.clear()

            conversation.refresh()

        self._run_non_blocking(_clear_on_ui)

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
        """Start the animation loop (called WITHOUT lock held to avoid deadlock)."""
        with self._lock:
            if self._running:
                return
            self._running = True

        # Schedule tick OUTSIDE lock to avoid deadlock
        # (_on_tick also acquires the lock)
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

        # Cancel existing timers (thread-safe operations)
        if self._textual_timer is not None:
            try:
                self._textual_timer.stop()
            except Exception:
                pass
        if self._thread_timer is not None:
            self._thread_timer.cancel()
            self._thread_timer = None

        # Schedule Textual timer - MUST be done on UI thread
        def _setup_textual_timer():
            try:
                self._textual_timer = self.app.set_timer(interval_sec, self._on_tick)
            except Exception:
                pass  # App may be shutting down

        # Dispatch to UI thread (non-blocking)
        self._run_non_blocking(_setup_textual_timer)

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

    def _render_initial_frame_blocking(self, spinner_id: str, display_text: Text) -> None:
        """Render the initial spinner frame with blocking call.

        This ensures the first frame is visible immediately before start() returns.
        Uses the first animation character (⠋) with elapsed time of 0.

        Args:
            spinner_id: The spinner ID
            display_text: The display text for the spinner
        """
        line_num = self._spinner_lines.get(spinner_id)
        if line_num is None:
            return

        conversation = self._conversation
        if conversation is None:
            return

        config = SPINNER_CONFIGS[SpinnerType.TOOL]

        def _update_on_ui():
            try:
                if line_num >= len(conversation.lines):
                    return

                # Build initial animated line: "⠋ Tool description (0s)"
                formatted = Text()
                formatted.append(f"{config.chars[0]} ", style=config.style)
                formatted.append_text(display_text)
                formatted.append(" (0s)", style=GREY)

                # Convert to Strip
                from rich.console import Console
                from textual.strip import Strip
                console = Console(width=1000, force_terminal=True, no_color=False)
                segments = list(formatted.render(console))
                strip = Strip(segments)

                # STRATEGY: Delete & Insert to force update
                if line_num < len(conversation.lines):
                    del conversation.lines[line_num]
                    conversation.lines.insert(line_num, strip)

                # Invalidate cache and refresh - BOTH refreshes are needed
                if hasattr(conversation, 'refresh_line'):
                    conversation.refresh_line(line_num)
                else:
                    conversation.refresh()

                # Also refresh the app (like DefaultSpinnerManager does)
                if hasattr(self.app, 'refresh'):
                    self.app.refresh()
            except Exception:
                pass  # Silently ignore errors

        # BLOCKING call to ensure initial frame is visible before returning
        self._run_blocking(_update_on_ui)

    def _render_facade_spinner(self, spinner_id: str, frame: SpinnerFrame) -> None:
        """Render a facade-API spinner by updating its specific line.

        This method updates the spinner line in-place, allowing parallel spinners
        to animate independently without overwriting each other.

        Args:
            spinner_id: The spinner ID to render
            frame: The current animation frame data
        """
        line_num = self._spinner_lines.get(spinner_id)
        display_text = self._spinner_displays.get(spinner_id)

        if line_num is None or display_text is None:
            return

        conversation = self._conversation
        if conversation is None:
            return

        def _update_on_ui():
            try:
                if line_num >= len(conversation.lines):
                    return

                # Build animated line: "⠋ Tool description (5s)"
                elapsed = frame.elapsed_seconds
                formatted = Text()
                formatted.append(f"{frame.char} ", style=frame.style)
                formatted.append_text(display_text)
                formatted.append(f" ({elapsed}s)", style=GREY)

                # Convert to Strip
                from rich.console import Console
                from textual.strip import Strip
                console = Console(width=1000, force_terminal=True, no_color=False)
                segments = list(formatted.render(console))
                strip = Strip(segments)

                # STRATEGY: Delete & Insert to force RichLog/Textual to recognize update
                # (same approach as DefaultSpinnerManager)
                if line_num < len(conversation.lines):
                    del conversation.lines[line_num]
                    conversation.lines.insert(line_num, strip)

                # Invalidate cache and refresh - BOTH refreshes are needed
                if hasattr(conversation, 'refresh_line'):
                    conversation.refresh_line(line_num)
                else:
                    conversation.refresh()

                # Also refresh the app (like DefaultSpinnerManager does)
                if hasattr(self.app, 'refresh'):
                    self.app.refresh()
            except Exception:
                pass  # Silently ignore errors in animation update

        # Run on UI thread (handles both UI thread and background thread cases)
        self._run_non_blocking(_update_on_ui)


__all__ = [
    "SpinnerService",
    "SpinnerType",
    "SpinnerConfig",
    "SpinnerFrame",
    "SpinnerInstance",
    "SPINNER_CONFIGS",
    "get_spinner_config",
]
