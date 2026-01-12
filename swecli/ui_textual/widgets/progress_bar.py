"""Animated progress bar widget with pulsing blue gradient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from rich.text import Text
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.timer import Timer

# Block characters from lightest to darkest shade
BLOCK_LIGHT = "░"
BLOCK_MEDIUM = "▒"
BLOCK_DARK = "▓"
BLOCK_FULL = "█"

# Blue gradient colors (dark to luminous)
BLUE_DARK = "#1a3a5c"
BLUE_MEDIUM = "#2563eb"
BLUE_BRIGHT = "#3b82f6"
BLUE_LIGHT = "#60a5fa"
BLUE_LUMINOUS = "#93c5fd"

# Bar configuration
BAR_WIDTH = 40
PULSE_WIDTH = 8  # How wide the bright pulse is
FRAME_INTERVAL_MS = 50  # 20fps for smooth animation


class ProgressBar(Static):
    """Animated horizontal progress bar with pulsing blue gradient.

    Displays a 40-character wide progress bar using block characters.
    A "pulse" of brightness sweeps continuously from left to right.
    Shows during task processing, hides when idle.

    The progress bar polls app._is_processing to determine when to show/hide,
    avoiding threading issues from direct show/hide calls.
    """

    def __init__(self, **kwargs) -> None:
        # Initialize with empty content to avoid None render issues
        super().__init__("", **kwargs)
        self._animation_timer: Optional["Timer"] = None
        self._poll_timer: Optional["Timer"] = None
        self._pulse_position: int = 0
        self._visible: bool = False
        self._app: Any = None

    def set_app(self, app: Any) -> None:
        """Set the app reference to poll processing state."""
        self._app = app

    def on_mount(self) -> None:
        """Start polling for processing state."""
        self.display = False
        # Poll every 100ms to check if processing is active
        self._poll_timer = self.set_interval(0.1, self._poll_processing_state)

    def _poll_processing_state(self) -> None:
        """Check if app is processing and show/hide accordingly."""
        if self._app is None:
            return

        is_processing = getattr(self._app, "_is_processing", False)

        if is_processing and not self._visible:
            self._show()
        elif not is_processing and self._visible:
            self._hide()

    def _show(self) -> None:
        """Start the progress bar animation."""
        if self._visible:
            return

        self._visible = True
        self._pulse_position = 0
        self.display = True

        # Start animation timer
        self._animation_timer = self.set_interval(
            FRAME_INTERVAL_MS / 1000,
            self._on_frame,
            pause=False,
        )

        # Render initial frame
        self._render_bar()

    def _hide(self) -> None:
        """Stop the progress bar animation and hide."""
        if not self._visible:
            return

        self._visible = False

        if self._animation_timer is not None:
            self._animation_timer.stop()
            self._animation_timer = None

        self._pulse_position = 0
        self.update(" ")  # Keep non-empty to avoid render issues
        self.display = False

    def _on_frame(self) -> None:
        """Handle animation frame - advance pulse and render."""
        if not self._visible:
            return

        # Advance pulse position (wraps around)
        self._pulse_position = (self._pulse_position + 1) % BAR_WIDTH
        self._render_bar()

    def _render_bar(self) -> None:
        """Render the progress bar with pulse at current position."""
        result = Text()

        for i in range(BAR_WIDTH):
            # Calculate distance from pulse center (with wrapping)
            dist = min(
                abs(i - self._pulse_position),
                abs(i - self._pulse_position + BAR_WIDTH),
                abs(i - self._pulse_position - BAR_WIDTH),
            )

            # Map distance to color and character
            if dist == 0:
                # Peak of pulse - brightest
                char = BLOCK_FULL
                color = BLUE_LUMINOUS
            elif dist <= 2:
                # Near peak
                char = BLOCK_FULL
                color = BLUE_LIGHT
            elif dist <= 4:
                # Trailing edge
                char = BLOCK_DARK
                color = BLUE_BRIGHT
            elif dist <= 6:
                # Far trailing edge
                char = BLOCK_MEDIUM
                color = BLUE_MEDIUM
            else:
                # Background
                char = BLOCK_LIGHT
                color = BLUE_DARK

            result.append(char, style=color)

        self.update(result)

    def on_unmount(self) -> None:
        """Clean up when widget is removed."""
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        self._hide()


__all__ = ["ProgressBar"]
