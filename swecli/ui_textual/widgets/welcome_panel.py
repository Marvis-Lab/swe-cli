"""Animated welcome panel widget with gradient color wave effect and spinning ASCII donut."""

from __future__ import annotations

import colorsys
import math
import os
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

from rich.align import Align
from rich.columns import Columns
from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget

from swecli.core.runtime import OperationMode

if TYPE_CHECKING:
    pass

__all__ = ["AnimatedWelcomePanel", "DonutRenderer"]


def hsl_to_ansi256(hue: float, saturation: float = 0.7, lightness: float = 0.6) -> int:
    """Convert HSL to closest ANSI-256 color code.

    Args:
        hue: Hue value (0-360)
        saturation: Saturation (0-1)
        lightness: Lightness (0-1)

    Returns:
        ANSI-256 color code (16-231 for color cube)
    """
    # Normalize hue to 0-1
    h = (hue % 360) / 360.0

    # Convert HSL to RGB
    r, g, b = colorsys.hls_to_rgb(h, lightness, saturation)

    # Convert RGB (0-1) to 6-level values (0-5) for ANSI color cube
    r6 = int(round(r * 5))
    g6 = int(round(g * 5))
    b6 = int(round(b * 5))

    # ANSI color cube: 16 + 36*r + 6*g + b
    return 16 + 36 * r6 + 6 * g6 + b6


class DonutRenderer:
    """Renders a spinning 3D ASCII torus (donut).

    Based on the famous donut.c algorithm by Andy Sloane.
    Uses parametric equations for a torus with z-buffer depth sorting
    and luminance-based ASCII character mapping.
    """

    # Luminance characters (dark to bright based on surface normal angle to light)
    CHARS = ".,-~:;=!*#$@"

    def __init__(self, width: int = 30, height: int = 15):
        """Initialize the donut renderer.

        Args:
            width: Output width in characters
            height: Output height in characters
        """
        self.width = width
        self.height = height
        # Start with initial rotation for a nice 3D view
        self.A = 1.0  # X-axis rotation angle (tilted forward)
        self.B = 0.5  # Z-axis rotation angle (slight turn)

        # Sampling density for torus surface
        self._theta_step = 0.07
        self._phi_step = 0.02

    def render_frame(self) -> list[list[tuple[str, float]]]:
        """Render one frame of the spinning donut.

        Returns:
            2D grid of (character, depth) tuples where depth is 1/z (higher = closer)
        """
        # Initialize output buffer and z-buffer
        output = [[(" ", 0.0) for _ in range(self.width)] for _ in range(self.height)]
        zbuffer = [[0.0 for _ in range(self.width)] for _ in range(self.height)]

        # Torus parameters
        R1 = 1.0  # Radius of the tube (cross-section)
        R2 = 2.0  # Distance from center of torus to center of tube
        K2 = 5.0  # Distance from viewer to donut

        # K1 controls the scale - calculated to fit the donut in the viewport
        K1 = self.width * K2 * 3 / (8 * (R1 + R2))

        # Precompute rotation sin/cos
        cos_A, sin_A = math.cos(self.A), math.sin(self.A)
        cos_B, sin_B = math.cos(self.B), math.sin(self.B)

        # Sample the torus surface
        theta = 0.0
        while theta < 2 * math.pi:
            cos_t, sin_t = math.cos(theta), math.sin(theta)

            phi = 0.0
            while phi < 2 * math.pi:
                cos_p, sin_p = math.cos(phi), math.sin(phi)

                # 3D coordinates on torus surface (before rotation)
                # Circle in x-z plane, then sweep around y-axis
                circle_x = R2 + R1 * cos_t
                circle_y = R1 * sin_t

                # Apply 3D rotations (rotate around x-axis by A, then z-axis by B)
                x = circle_x * (cos_B * cos_p + sin_A * sin_B * sin_p) - circle_y * cos_A * sin_B
                y = circle_x * (sin_B * cos_p - sin_A * cos_B * sin_p) + circle_y * cos_A * cos_B
                z = K2 + cos_A * circle_x * sin_p + circle_y * sin_A
                ooz = 1.0 / z  # One over z (for z-buffer and projection)

                # Project 3D to 2D screen coordinates
                xp = int(self.width / 2 + K1 * ooz * x)
                yp = int(self.height / 2 - K1 * ooz * y * 0.5)  # 0.5 for aspect ratio

                # Calculate luminance based on surface normal dot light direction
                # Light comes from upper-left-front
                L = (
                    cos_p * cos_t * sin_B
                    - cos_A * cos_t * sin_p
                    - sin_A * sin_t
                    + cos_B * (cos_A * sin_t - cos_t * sin_A * sin_p)
                )

                # Only render if within bounds and in front of what's already there
                if 0 <= xp < self.width and 0 <= yp < self.height:
                    if ooz > zbuffer[yp][xp]:
                        zbuffer[yp][xp] = ooz
                        # Map luminance to character (L ranges roughly -1 to 1)
                        lum_idx = int((L + 1) * 4)  # Scale to 0-8 range
                        lum_idx = max(0, min(lum_idx, len(self.CHARS) - 1))
                        char = self.CHARS[lum_idx]
                        output[yp][xp] = (char, ooz)

                phi += self._phi_step
            theta += self._theta_step

        return output

    def step(self) -> None:
        """Advance animation by one frame."""
        self.A += 0.04  # Rotation speed around X
        self.B += 0.02  # Rotation speed around Z


class AnimatedWelcomePanel(Widget):
    """Animated welcome panel with gradient color wave effect.

    Features:
    - Rainbow gradient that waves across the text
    - Smooth fade-out animation on dismiss
    - Responsive centering
    """

    DEFAULT_CSS = """
    AnimatedWelcomePanel {
        width: 100%;
        height: auto;
        padding: 1 2;
        content-align: center middle;
    }
    """

    # Reactive properties for animation state
    gradient_offset: reactive[int] = reactive(0)
    fade_progress: reactive[float] = reactive(1.0)

    def __init__(
        self,
        current_mode: OperationMode = OperationMode.NORMAL,
        working_dir: Optional[Path] = None,
        username: Optional[str] = None,
        on_fade_complete: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        """Initialize the animated welcome panel.

        Args:
            current_mode: Current operation mode (NORMAL/PLAN)
            working_dir: Working directory path
            username: User's name for greeting
            on_fade_complete: Callback when fade-out animation completes
        """
        super().__init__(**kwargs)
        self._current_mode = current_mode
        self._working_dir = working_dir or Path.cwd()
        self._username = username or os.getenv("USER", "Developer")
        self._on_fade_complete = on_fade_complete
        self._animation_timer: Optional[Timer] = None
        self._fade_timer: Optional[Timer] = None
        self._is_fading = False

        # Initialize the spinning donut renderer (compact size for side-by-side)
        self._donut = DonutRenderer(width=28, height=14)

        # Cache the plain text content for gradient coloring
        self._content_lines = self._generate_content()

    @staticmethod
    def get_version() -> str:
        """Get SWE-CLI version."""
        try:
            from importlib.metadata import version

            return f"v{version('swecli')}"
        except Exception:
            return "v0.1.7"

    def _generate_content(self) -> list[str]:
        """Generate welcome content lines without colors.

        Returns:
            List of plain text lines for gradient coloring
        """
        version = self.get_version()
        user = self._username.strip() or "Developer"
        mode = self._current_mode.value.upper()

        # Create compact, visually appealing content
        lines = [
            "",
            f"Welcome back {user}!",
            "",
            "╔═══════════╗",
            "║  SWE-CLI  ║",
            "╚═══════════╝",
            "",
            f"Version {version}",
            f"Mode: {mode}",
            "",
            "Essential Commands:",
            "  /help      Show all commands",
            "  /models    Configure AI models",
            "  /mode      Toggle plan/normal mode",
            "",
            "Keyboard Shortcuts:",
            "  Shift+Tab  Toggle mode",
            "  @file      Mention file for context",
            "  ↑ / ↓      Navigate history",
            "",
        ]
        return lines

    def on_mount(self) -> None:
        """Start gradient animation on mount."""
        self._animation_timer = self.set_interval(0.05, self._update_gradient)

    def on_unmount(self) -> None:
        """Clean up timers on unmount."""
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer = None
        if self._fade_timer:
            self._fade_timer.stop()
            self._fade_timer = None

    def _update_gradient(self) -> None:
        """Advance gradient wave and donut rotation animations."""
        if self._is_fading:
            return
        # Shift gradient offset (5 degrees per frame = full cycle in ~3.6s)
        self.gradient_offset = (self.gradient_offset + 5) % 360
        # Advance donut rotation
        self._donut.step()

    def _do_fade(self) -> None:
        """Execute one fade animation step."""
        new_progress = self.fade_progress - 0.08  # ~12 frames to fully fade

        if new_progress <= 0:
            self.fade_progress = 0
            if self._fade_timer:
                self._fade_timer.stop()
                self._fade_timer = None
            if self._on_fade_complete:
                self._on_fade_complete()
        else:
            self.fade_progress = new_progress

    def fade_out(self, callback: Optional[Callable[[], None]] = None) -> None:
        """Start fade-out animation.

        Args:
            callback: Optional callback to invoke when fade completes
        """
        if self._is_fading:
            return

        self._is_fading = True
        if callback:
            self._on_fade_complete = callback

        # Stop gradient animation
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer = None

        # Start fade animation
        self._fade_timer = self.set_interval(0.025, self._do_fade)

    def _apply_gradient(self, text: str, line_offset: int = 0) -> Text:
        """Apply gradient coloring to text.

        Args:
            text: Plain text to colorize
            line_offset: Vertical offset for wave effect

        Returns:
            Rich Text object with gradient colors
        """
        result = Text()

        for i, char in enumerate(text):
            if char.isspace():
                result.append(char)
                continue

            # Calculate hue based on character position and animation offset
            # Add line_offset to create vertical wave effect
            hue = (i * 8 + line_offset * 20 + self.gradient_offset) % 360

            # Apply fade by reducing saturation and moving toward gray
            saturation = 0.8 * self.fade_progress
            lightness = 0.6 * self.fade_progress + 0.1 * (1 - self.fade_progress)

            color_code = hsl_to_ansi256(hue, saturation, lightness)
            result.append(char, style=f"color({color_code})")

        return result

    def _render_donut(self) -> Text:
        """Render the spinning donut with gradient coloring.

        Returns:
            Rich Text object containing the colored ASCII donut
        """
        donut_text = Text()
        donut_frame = self._donut.render_frame()

        for row_idx, row in enumerate(donut_frame):
            if row_idx > 0:
                donut_text.append("\n")

            for col_idx, (char, depth) in enumerate(row):
                if char != " ":
                    # Color based on depth and gradient offset for flowing effect
                    # Depth is 1/z, so higher = closer, use it to shift hue
                    hue = (depth * 600 + col_idx * 5 + row_idx * 8 + self.gradient_offset) % 360

                    # Apply fade by reducing saturation and lightness
                    saturation = 0.75 * self.fade_progress
                    lightness = 0.55 * self.fade_progress + 0.1 * (1 - self.fade_progress)

                    color_code = hsl_to_ansi256(hue, saturation, lightness)
                    donut_text.append(char, style=f"color({color_code})")
                else:
                    donut_text.append(char)

        return donut_text

    def _render_welcome_text(self) -> Text:
        """Render welcome content with gradient coloring.

        Returns:
            Rich Text object with gradient-colored welcome text
        """
        content = Text()

        for line_idx, line in enumerate(self._content_lines):
            if line_idx > 0:
                content.append("\n")

            if line:
                colored_line = self._apply_gradient(line, line_idx)
                content.append_text(colored_line)

        return content

    def _get_border_style(self) -> str:
        """Get border style based on fade progress."""
        # Cycle border color with gradient
        hue = self.gradient_offset % 360
        saturation = 0.6 * self.fade_progress
        lightness = 0.5 * self.fade_progress + 0.15 * (1 - self.fade_progress)

        color_code = hsl_to_ansi256(hue, saturation, lightness)
        return f"color({color_code})"

    def render(self) -> RenderableType:
        """Render the animated welcome panel with side-by-side donut and text."""
        # Render both components
        donut = self._render_donut()
        welcome_text = self._render_welcome_text()

        # Use Rich Columns for side-by-side layout
        # Donut on the left, welcome text on the right
        columns = Columns(
            [Align.center(donut), Align.center(welcome_text)],
            padding=2,
            expand=False,
        )

        # Create centered panel with responsive width
        panel_width = min(85, self.size.width - 4) if self.size.width > 0 else 85

        panel = Panel(
            Align.center(columns),
            border_style=self._get_border_style(),
            padding=(1, 2),
            width=panel_width,
        )

        return Align.center(panel)

    def watch_gradient_offset(self, _: int) -> None:
        """React to gradient offset changes."""
        self.refresh()

    def watch_fade_progress(self, _: float) -> None:
        """React to fade progress changes."""
        self.refresh()
