"""Animated welcome panel widget with gradient color wave effect and spinning 3D cube."""

from __future__ import annotations

import colorsys
import math
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

__all__ = ["AnimatedWelcomePanel", "CubeRenderer"]


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


class CubeRenderer:
    """Renders a spinning 3D wireframe cube.

    Draws a cube with 8 vertices and 12 edges, rotating smoothly
    in 3D space with perspective projection and line drawing.
    """

    # Edge characters for wireframe rendering
    EDGE_CHAR = "#"

    # Terminal character aspect ratio (height/width) - typically ~2.0
    CHAR_ASPECT = 2.0

    def __init__(self, width: int = 35, height: int = 18):
        """Initialize the cube renderer.

        Args:
            width: Output width in characters
            height: Output height in characters
        """
        self.width = width
        self.height = height

        # Rotation angles around each axis
        self.angle_x = 0.5  # Initial tilt for nice 3D view
        self.angle_y = 0.3
        self.angle_z = 0.0

        # Define cube vertices (normalized -1 to 1)
        self._vertices = [
            (-1, -1, -1),  # 0: back-bottom-left
            (1, -1, -1),  # 1: back-bottom-right
            (1, 1, -1),  # 2: back-top-right
            (-1, 1, -1),  # 3: back-top-left
            (-1, -1, 1),  # 4: front-bottom-left
            (1, -1, 1),  # 5: front-bottom-right
            (1, 1, 1),  # 6: front-top-right
            (-1, 1, 1),  # 7: front-top-left
        ]

        # Define edges as pairs of vertex indices
        self._edges = [
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 0),  # Back face
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 4),  # Front face
            (0, 4),
            (1, 5),
            (2, 6),
            (3, 7),  # Connecting edges
        ]

    def _rotate_point(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        """Apply 3D rotation to a point.

        Args:
            x, y, z: Point coordinates

        Returns:
            Rotated (x, y, z) coordinates
        """
        # Rotation around X axis
        cos_x, sin_x = math.cos(self.angle_x), math.sin(self.angle_x)
        y, z = y * cos_x - z * sin_x, y * sin_x + z * cos_x

        # Rotation around Y axis
        cos_y, sin_y = math.cos(self.angle_y), math.sin(self.angle_y)
        x, z = x * cos_y + z * sin_y, -x * sin_y + z * cos_y

        # Rotation around Z axis
        cos_z, sin_z = math.cos(self.angle_z), math.sin(self.angle_z)
        x, y = x * cos_z - y * sin_z, x * sin_z + y * cos_z

        return x, y, z

    def _project_point(self, x: float, y: float, z: float) -> tuple[int, int, float]:
        """Project 3D point to 2D screen coordinates with perspective.

        Args:
            x, y, z: 3D point coordinates

        Returns:
            Tuple of (screen_x, screen_y, depth) where depth is 1/(z+distance)
        """
        # Distance from viewer to cube center
        distance = 4.0

        # Perspective projection
        z_offset = z + distance
        if z_offset <= 0.1:
            z_offset = 0.1  # Prevent division by zero

        # Scale factor based on viewport size (0.45 for larger cube in vertical layout)
        effective_height = self.height * self.CHAR_ASPECT
        scale = min(self.width, effective_height) * 0.45

        # Project to 2D with perspective
        screen_x = int(self.width / 2 + (x * scale) / z_offset)
        screen_y = int(self.height / 2 - (y * scale) / (z_offset * self.CHAR_ASPECT))

        depth = 1.0 / z_offset  # Higher = closer

        return screen_x, screen_y, depth

    def _draw_line(
        self,
        output: list[list[tuple[str, float]]],
        x0: int,
        y0: int,
        depth0: float,
        x1: int,
        y1: int,
        depth1: float,
        edge_index: int,
    ) -> None:
        """Draw a line between two points using Bresenham's algorithm.

        Args:
            output: 2D output grid to draw into
            x0, y0: Start point screen coordinates
            depth0: Depth at start point
            x1, y1: End point screen coordinates
            depth1: Depth at end point
            edge_index: Index of this edge (for coloring)
        """
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        # Total distance for depth interpolation
        total_dist = max(dx, dy, 1)
        step_count = 0

        x, y = x0, y0

        while True:
            # Interpolate depth along the line
            t = step_count / total_dist if total_dist > 0 else 0
            depth = depth0 * (1 - t) + depth1 * t

            # Draw if within bounds
            if 0 <= x < self.width and 0 <= y < self.height:
                # Store character with depth and edge index for coloring
                # Use edge_index as part of the depth value for color variation
                color_depth = depth + edge_index * 0.01
                if output[y][x][1] < depth:  # Z-buffer check
                    output[y][x] = (self.EDGE_CHAR, color_depth)

            if x == x1 and y == y1:
                break

            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

            step_count += 1

    def render_frame(self) -> list[list[tuple[str, float]]]:
        """Render one frame of the spinning cube.

        Returns:
            2D grid of (character, depth) tuples where depth is 1/z (higher = closer)
        """
        # Initialize output buffer
        output = [[(" ", 0.0) for _ in range(self.width)] for _ in range(self.height)]

        # Transform all vertices
        projected = []
        for vx, vy, vz in self._vertices:
            # Rotate the vertex
            rx, ry, rz = self._rotate_point(vx, vy, vz)
            # Project to screen
            sx, sy, depth = self._project_point(rx, ry, rz)
            projected.append((sx, sy, depth))

        # Draw all edges
        for edge_idx, (v0, v1) in enumerate(self._edges):
            x0, y0, d0 = projected[v0]
            x1, y1, d1 = projected[v1]
            self._draw_line(output, x0, y0, d0, x1, y1, d1, edge_idx)

        return output

    def step(self) -> None:
        """Advance animation by one frame."""
        self.angle_x += 0.03  # Rotation speed around X
        self.angle_y += 0.04  # Rotation speed around Y
        self.angle_z += 0.01  # Rotation speed around Z


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
        height: 100%;
        align: center middle;
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

        # Initialize the spinning cube renderer with default size
        # Size will be recalculated dynamically based on terminal dimensions
        self._cube = CubeRenderer(width=30, height=15)
        self._last_cube_size: tuple[int, int] = (30, 15)

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
        """Generate horizontally spread welcome content.

        Returns:
            List of strings for welcome text section (spread horizontally)
        """
        version = self.get_version()
        mode = self._current_mode.value.upper()

        # Horizontal spread layout - 3 lines max
        lines = [
            f"═══  S W E - C L I  {version}  ═══  Mode: {mode}  ═══",
            "",
            "/help  │  /models  │  Shift+Tab plan mode  │  @file context",
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
        """Advance gradient wave and cube rotation animations."""
        if self._is_fading:
            return
        # Shift gradient offset (5 degrees per frame = full cycle in ~3.6s)
        self.gradient_offset = (self.gradient_offset + 5) % 360
        # Advance cube rotation
        self._cube.step()

    def _calculate_cube_size(self) -> tuple[int, int]:
        """Calculate dynamic cube size based on terminal dimensions.

        Horizontal style - wider cube, shorter height.

        Returns:
            Tuple of (width, height) for the cube renderer
        """
        # Get available space
        term_width = self.size.width if self.size.width > 0 else 100
        term_height = self.size.height if self.size.height > 0 else 30

        # Wide horizontal cube - use more width
        available_width = term_width - 20
        cube_width = max(50, min(80, int(available_width * 0.7)))

        # Shorter height for horizontal look (less than standard aspect)
        cube_height = max(8, min(14, int(cube_width / 4)))

        # Reserve space for text lines below
        max_height = max(8, term_height - 10)
        cube_height = min(cube_height, max_height)

        return (cube_width, cube_height)

    def _update_cube_size(self) -> None:
        """Update cube renderer size if terminal dimensions changed."""
        new_size = self._calculate_cube_size()
        if new_size != self._last_cube_size:
            self._cube.width, self._cube.height = new_size
            self._last_cube_size = new_size

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

    def _render_cube(self) -> Text:
        """Render the spinning cube with rainbow gradient coloring.

        Returns:
            Rich Text object containing the colored ASCII cube
        """
        cube_text = Text()
        cube_frame = self._cube.render_frame()

        for row_idx, row in enumerate(cube_frame):
            if row_idx > 0:
                cube_text.append("\n")

            for col_idx, (char, depth) in enumerate(row):
                if char != " ":
                    # Color based on depth and gradient offset for flowing rainbow effect
                    # The edge index is encoded in the fractional part of depth
                    hue = (depth * 800 + col_idx * 6 + row_idx * 10 + self.gradient_offset) % 360

                    # Apply fade by reducing saturation and lightness
                    saturation = 0.85 * self.fade_progress
                    lightness = 0.55 * self.fade_progress + 0.1 * (1 - self.fade_progress)

                    color_code = hsl_to_ansi256(hue, saturation, lightness)
                    cube_text.append(char, style=f"color({color_code})")
                else:
                    cube_text.append(char)

        return cube_text

    def _render_welcome_text(self) -> Text:
        """Render welcome content with gradient coloring.

        Returns:
            Rich Text object with gradient-colored multi-line welcome text
        """
        result = Text(justify="center")

        for line_idx, line in enumerate(self._content_lines):
            if line_idx > 0:
                result.append("\n")
            # Apply gradient with vertical wave offset for each line
            result.append_text(self._apply_gradient(line, line_idx))

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
        """Render the animated welcome panel: cube on top, horizontal text below."""
        from rich.console import Group

        # Update cube size based on current terminal dimensions
        self._update_cube_size()

        # Render both components
        cube = self._render_cube()
        welcome_text = self._render_welcome_text()

        # Stack vertically: cube on top, horizontal text bar below
        content = Group(
            Align.center(cube),
            Text(""),  # Spacer
            Align.center(welcome_text),
        )

        # Calculate vertical padding to center the panel
        term_height = self.size.height if self.size.height > 0 else 30
        content_height = self._cube.height + len(self._content_lines) + 4
        vertical_padding = max(0, (term_height - content_height) // 3)

        # Panel auto-sizes to fit content
        panel = Panel(
            content,
            border_style=self._get_border_style(),
            padding=(0, 2),
        )

        # Add top padding for vertical centering
        from rich.text import Text as RichText

        top_padding = RichText("\n" * vertical_padding) if vertical_padding > 0 else RichText("")

        return Align.center(Group(top_padding, panel))

    def watch_gradient_offset(self, _: int) -> None:
        """React to gradient offset changes."""
        self.refresh()

    def watch_fade_progress(self, _: float) -> None:
        """React to fade progress changes."""
        self.refresh()
