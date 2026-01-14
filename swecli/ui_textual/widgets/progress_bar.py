"""Animated progress bar widget with sequential blue highlight sweep."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from rich.text import Text
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.timer import Timer

# Segment character - small dot that reads as bar when repeated
SEGMENT = "•"

# Blue color palette (dark base to bright highlight)
BLUE_BASE = "#2a4a6a"      # Resting state - muted dark blue
BLUE_DIM = "#3a5a7a"       # Slightly brightened
BLUE_MID = "#4a7090"       # Transitioning
BLUE_GLOW = "#6090b8"      # Approaching highlight
BLUE_BRIGHT = "#80b0d8"    # Near peak
BLUE_HIGHLIGHT = "#a8d0f0" # Peak brightness

# Bar configuration
BAR_WIDTH = 40
HIGHLIGHT_WIDTH = 6  # How many segments are affected by the highlight
FRAME_INTERVAL_MS = 50  # Smooth, steady timing


class ProgressBar(Static):
    """Animated progress bar with sequential highlight sweep.

    A short horizontal line of evenly spaced segments. A soft blue
    highlight travels from left to right, with each segment briefly
    brightening as it passes, then fading back to darker blue.
    Creates a clear, sequential rhythm emphasizing direction and continuity.

    The progress bar polls app._is_processing to determine when to show/hide,
    avoiding threading issues from direct show/hide calls.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._animation_timer: Optional["Timer"] = None
        self._poll_timer: Optional["Timer"] = None
        self._highlight_pos: int = 0
        self._visible: bool = False
        self._app: Any = None

    def set_app(self, app: Any) -> None:
        """Set the app reference to poll processing state."""
        self._app = app

    def on_mount(self) -> None:
        """Start polling for processing state."""
        self.display = False
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
        self._highlight_pos = 0
        self.display = True

        self._animation_timer = self.set_interval(
            FRAME_INTERVAL_MS / 1000,
            self._on_frame,
            pause=False,
        )

        self._render_bar()

    def _hide(self) -> None:
        """Stop the progress bar animation and hide."""
        if not self._visible:
            return

        self._visible = False

        if self._animation_timer is not None:
            self._animation_timer.stop()
            self._animation_timer = None

        self._highlight_pos = 0
        self.update(" ")
        self.display = False

    def _on_frame(self) -> None:
        """Advance highlight position and render."""
        if not self._visible:
            return

        self._highlight_pos = (self._highlight_pos + 1) % BAR_WIDTH
        self._render_bar()

    def _render_bar(self) -> None:
        """Render the bar with highlight at current position."""
        result = Text()

        for i in range(BAR_WIDTH):
            # Calculate distance from highlight center (with wrapping for seamless loop)
            dist = min(
                abs(i - self._highlight_pos),
                abs(i - self._highlight_pos + BAR_WIDTH),
                abs(i - self._highlight_pos - BAR_WIDTH),
            )

            # Map distance to color - closer = brighter
            color = self._get_color(dist)
            result.append(SEGMENT, style=color)

        self.update(result)

    def _get_color(self, distance: int) -> str:
        """Map distance from highlight to color.

        Creates smooth gradient: peak brightness at center,
        fading to base color further away.
        """
        if distance == 0:
            return BLUE_HIGHLIGHT
        elif distance == 1:
            return BLUE_BRIGHT
        elif distance == 2:
            return BLUE_GLOW
        elif distance == 3:
            return BLUE_MID
        elif distance <= 5:
            return BLUE_DIM
        else:
            return BLUE_BASE

    def on_unmount(self) -> None:
        """Clean up when widget is removed."""
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        self._hide()


__all__ = ["ProgressBar"]
