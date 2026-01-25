"""Animated welcome panel widget with gradient color wave effect."""

from __future__ import annotations

import colorsys
import os
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

from rich.align import Align
from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget

from swecli.core.runtime import OperationMode

if TYPE_CHECKING:
    pass

__all__ = ["AnimatedWelcomePanel"]


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
        """Advance gradient wave animation."""
        if self._is_fading:
            return
        # Shift gradient offset (5 degrees per frame = full cycle in ~3.6s)
        self.gradient_offset = (self.gradient_offset + 5) % 360

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

    def _get_border_style(self) -> str:
        """Get border style based on fade progress."""
        # Cycle border color with gradient
        hue = self.gradient_offset % 360
        saturation = 0.6 * self.fade_progress
        lightness = 0.5 * self.fade_progress + 0.15 * (1 - self.fade_progress)

        color_code = hsl_to_ansi256(hue, saturation, lightness)
        return f"color({color_code})"

    def render(self) -> RenderableType:
        """Render the animated welcome panel."""
        # Build gradient-colored content
        content = Text()

        for line_idx, line in enumerate(self._content_lines):
            if line_idx > 0:
                content.append("\n")

            if line:
                # Apply gradient with vertical wave offset
                colored_line = self._apply_gradient(line, line_idx)
                content.append_text(colored_line)

        # Create centered panel
        panel_width = min(50, self.size.width - 4) if self.size.width > 0 else 50

        panel = Panel(
            Align.center(content),
            border_style=self._get_border_style(),
            padding=(0, 2),
            width=panel_width,
        )

        return Align.center(panel)

    def watch_gradient_offset(self, _: int) -> None:
        """React to gradient offset changes."""
        self.refresh()

    def watch_fade_progress(self, _: float) -> None:
        """React to fade progress changes."""
        self.refresh()
