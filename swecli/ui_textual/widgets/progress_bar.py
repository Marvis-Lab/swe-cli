"""LED heartbeat progress bar.

A stealthy, utilitarian indicator: a row of inactive LEDs on a server rack
where a single, faint signal pulse travels across the line.

No glowing—just subtle spectral shift. Dots become "awake" (slate-blue)
then immediately return to "sleep" (dark indigo). Mechanical and precise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from rich.text import Text
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.timer import Timer


# Dot character - bullet for visible LED appearance
SEGMENT = "•"  # U+2022 - medium bullet, balanced size

# LED color palette - stark contrast between sleep and awake
COLOR_SLEEP = "#252540"    # Dark indigo - dim "off" state
COLOR_AWAKE = "#5a8fc4"    # Slate-blue - visible "on" state

# Configuration
BAR_WIDTH = 28             # Number of LED dots
FRAME_INTERVAL_MS = 50     # Animation speed (20 fps)
PULSE_WIDTH = 2            # Pulse width for visibility


class ProgressBar(Static):
    """LED heartbeat progress bar.

    A row of dark dots where a single pulse travels left to right,
    each dot briefly awakening then immediately returning to sleep.
    Constant velocity, no easing—mechanical and precise.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._animation_timer: Optional["Timer"] = None
        self._poll_timer: Optional["Timer"] = None
        self._pulse_pos: float = 0.0
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
        """Start the LED heartbeat animation."""
        if self._visible:
            return

        self._visible = True
        self._pulse_pos = 0.0
        self.display = True

        self._animation_timer = self.set_interval(
            FRAME_INTERVAL_MS / 1000,
            self._on_frame,
            pause=False,
        )

        self._render_leds()
        self.refresh()  # Force initial render

    def _hide(self) -> None:
        """Stop the animation and hide."""
        if not self._visible:
            return

        self._visible = False

        if self._animation_timer is not None:
            self._animation_timer.stop()
            self._animation_timer = None

        self._pulse_pos = 0.0
        self.update(" ")
        self.display = False

    def _on_frame(self) -> None:
        """Advance pulse position at constant velocity."""
        if not self._visible:
            return

        # Constant velocity - mechanical feel
        self._pulse_pos = (self._pulse_pos + 0.8) % BAR_WIDTH
        self._render_leds()

    def _render_leds(self) -> None:
        """Render LED row with traveling pulse."""
        result = Text()

        for i in range(BAR_WIDTH):
            color = self._get_led_color(i)
            result.append(SEGMENT, style=color)

        self.update(result)

    def _get_led_color(self, idx: int) -> str:
        """Get LED color: awake if pulse is here, sleep otherwise.

        Creates a tight single-dot pulse with minimal falloff.
        """
        # Distance from pulse (with wrapping)
        dist = min(
            abs(idx - self._pulse_pos),
            abs(idx - self._pulse_pos + BAR_WIDTH),
            abs(idx - self._pulse_pos - BAR_WIDTH),
        )

        if dist > PULSE_WIDTH:
            return COLOR_SLEEP

        # Sharp falloff - mostly binary on/off feel
        t = 1.0 - (dist / PULSE_WIDTH)
        t = t * t  # Square for sharper transition

        return self._lerp_hex(COLOR_SLEEP, COLOR_AWAKE, t)

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
