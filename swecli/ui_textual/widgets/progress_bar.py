"""Minimal animated progress bar with subtle luminance wave.

A restrained, precise loading indicator: small dots with a soft
brightness wave traveling left to right. No white, no glow, no
decorative effects—just calm, controlled color interpolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from rich.text import Text
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.timer import Timer


# Dot character - middle dot for pixel-like appearance
SEGMENT = "·"  # U+00B7 - smaller than bullet, terminal-appropriate

# Muted, low-contrast blue palette
# Never white, never neon, never glowing
BLUE_BASE = "#3a4a5a"      # Subdued blue-gray (visible on dark backgrounds)
BLUE_PEAK = "#5a7a90"      # Slightly brighter (subtle highlight, not glowing)

# Configuration
BAR_WIDTH = 32             # Compact width
FRAME_INTERVAL_MS = 60     # Smooth timing
WAVE_WIDTH = 2             # Tight, focused highlight (1-2 dots)


class ProgressBar(Static):
    """Minimal progress bar with subtle luminance wave.

    Small dots in a cohesive row. A soft wave travels left to right,
    each dot subtly brightening then fading back. Constant velocity,
    no acceleration, no easing—calm and controlled.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._animation_timer: Optional["Timer"] = None
        self._poll_timer: Optional["Timer"] = None
        self._wave_pos: float = 0.0
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
        self._wave_pos = 0.0
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

        self._wave_pos = 0.0
        self.update(" ")
        self.display = False

    def _on_frame(self) -> None:
        """Advance wave position at constant velocity."""
        if not self._visible:
            return

        # Constant velocity - no acceleration, no easing
        self._wave_pos = (self._wave_pos + 0.5) % BAR_WIDTH
        self._render_bar()

    def _render_bar(self) -> None:
        """Render bar with luminance wave."""
        result = Text()

        for i in range(BAR_WIDTH):
            color = self._get_color(i)
            result.append(SEGMENT, style=color)

        self.update(result)

    def _get_color(self, idx: int) -> str:
        """Get color for dot based on distance from wave center.

        Uses smooth interpolation - dots closer to wave are brighter,
        those further away fade to base. Narrow highlight, no white.
        """
        # Distance from wave (with wrapping for seamless loop)
        dist = min(
            abs(idx - self._wave_pos),
            abs(idx - self._wave_pos + BAR_WIDTH),
            abs(idx - self._wave_pos - BAR_WIDTH),
        )

        if dist >= WAVE_WIDTH:
            return BLUE_BASE

        # Smooth falloff: 1.0 at center, 0.0 at edge
        # Using simple linear falloff for constant, controlled feel
        t = 1.0 - (dist / WAVE_WIDTH)

        # Interpolate from base to peak
        return self._lerp_hex(BLUE_BASE, BLUE_PEAK, t)

    def _lerp_hex(self, color1: str, color2: str, t: float) -> str:
        """Linear interpolation between two hex colors."""
        r1, g1, b1 = self._hex_to_rgb(color1)
        r2, g2, b2 = self._hex_to_rgb(color2)

        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)

        return f"#{r:02x}{g:02x}{b:02x}"

    def _hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        """Convert hex to RGB tuple."""
        h = hex_color.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def on_unmount(self) -> None:
        """Clean up when widget is removed."""
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        self._hide()


__all__ = ["ProgressBar"]
