"""Animated welcome panel widget with gradient color wave effect and spinning 3D shapes."""

from __future__ import annotations

import colorsys
import math
import os
from abc import ABC, abstractmethod
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

__all__ = ["AnimatedWelcomePanel", "CubeRenderer", "PyramidRenderer", "OctahedronRenderer"]


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


class Shape3DRenderer(ABC):
    """Base class for 3D wireframe shape renderers.

    Provides common rotation, projection, and line drawing logic.
    Subclasses define vertices and edges for specific shapes.
    """

    # Edge characters for wireframe rendering
    EDGE_CHAR = "#"

    # Terminal character aspect ratio (height/width) - typically ~2.0
    CHAR_ASPECT = 2.0

    def __init__(
        self,
        width: int = 35,
        height: int = 18,
        initial_x: float = 0.5,
        initial_y: float = 0.3,
        initial_z: float = 0.0,
        speed_x: float = 0.03,
        speed_y: float = 0.04,
        speed_z: float = 0.01,
    ):
        """Initialize the shape renderer.

        Args:
            width: Output width in characters
            height: Output height in characters
            initial_x/y/z: Initial rotation angles
            speed_x/y/z: Rotation speeds per frame
        """
        self.width = width
        self.height = height

        # Rotation angles around each axis
        self.angle_x = initial_x
        self.angle_y = initial_y
        self.angle_z = initial_z

        # Rotation speeds
        self._speed_x = speed_x
        self._speed_y = speed_y
        self._speed_z = speed_z

        # Subclasses define these
        self._vertices: list[tuple[float, float, float]] = []
        self._edges: list[tuple[int, int]] = []

    @abstractmethod
    def _init_geometry(self) -> None:
        """Initialize vertices and edges for this shape."""
        pass


class CubeRenderer(Shape3DRenderer):
    """Renders a spinning 3D wireframe cube.

    Draws a cube with 8 vertices and 12 edges, rotating smoothly
    in 3D space with perspective projection and line drawing.
    """

    def __init__(self, width: int = 35, height: int = 18):
        """Initialize the cube renderer."""
        super().__init__(width, height, speed_x=0.03, speed_y=0.04, speed_z=0.01)
        self._init_geometry()

    def _init_geometry(self) -> None:
        """Initialize cube vertices and edges."""
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


class PyramidRenderer(Shape3DRenderer):
    """Renders a spinning 3D wireframe pyramid (tetrahedron).

    Draws a tetrahedron with 4 vertices and 6 edges.
    """

    def __init__(self, width: int = 35, height: int = 18):
        """Initialize the pyramid renderer."""
        # Different rotation speeds for visual variety
        super().__init__(width, height, speed_x=0.04, speed_y=0.03, speed_z=0.02)
        self._init_geometry()

    def _init_geometry(self) -> None:
        """Initialize tetrahedron vertices and edges."""
        # Regular tetrahedron vertices
        self._vertices = [
            (0, 1.2, 0),  # Top apex
            (-1, -0.6, 0.7),  # Base front-left
            (1, -0.6, 0.7),  # Base front-right
            (0, -0.6, -1),  # Base back
        ]

        # All edges connecting the 4 vertices
        self._edges = [
            (0, 1),
            (0, 2),
            (0, 3),  # Apex to base
            (1, 2),
            (2, 3),
            (3, 1),  # Base triangle
        ]


class OctahedronRenderer(Shape3DRenderer):
    """Renders a spinning 3D wireframe octahedron.

    Draws an octahedron with 6 vertices and 12 edges (diamond shape).
    """

    def __init__(self, width: int = 35, height: int = 18):
        """Initialize the octahedron renderer."""
        # Different rotation speeds for visual variety
        super().__init__(width, height, speed_x=0.025, speed_y=0.05, speed_z=0.015)
        self._init_geometry()

    def _init_geometry(self) -> None:
        """Initialize octahedron vertices and edges."""
        # Octahedron vertices - 6 points along axes
        self._vertices = [
            (0, 1.2, 0),  # Top
            (0, -1.2, 0),  # Bottom
            (1, 0, 0),  # Right
            (-1, 0, 0),  # Left
            (0, 0, 1),  # Front
            (0, 0, -1),  # Back
        ]

        # 12 edges forming 8 triangular faces
        self._edges = [
            (0, 2),
            (0, 3),
            (0, 4),
            (0, 5),  # Top to middle ring
            (1, 2),
            (1, 3),
            (1, 4),
            (1, 5),  # Bottom to middle ring
            (2, 4),
            (4, 3),
            (3, 5),
            (5, 2),  # Middle ring
        ]


# Add common methods to Shape3DRenderer
def _rotate_point(self, x: float, y: float, z: float) -> tuple[float, float, float]:
    """Apply 3D rotation to a point."""
    cos_x, sin_x = math.cos(self.angle_x), math.sin(self.angle_x)
    y, z = y * cos_x - z * sin_x, y * sin_x + z * cos_x

    cos_y, sin_y = math.cos(self.angle_y), math.sin(self.angle_y)
    x, z = x * cos_y + z * sin_y, -x * sin_y + z * cos_y

    cos_z, sin_z = math.cos(self.angle_z), math.sin(self.angle_z)
    x, y = x * cos_z - y * sin_z, x * sin_z + y * cos_z

    return x, y, z


def _project_point(self, x: float, y: float, z: float) -> tuple[int, int, float]:
    """Project 3D point to 2D screen coordinates with perspective."""
    distance = 4.0
    z_offset = z + distance
    if z_offset <= 0.1:
        z_offset = 0.1

    effective_height = self.height * Shape3DRenderer.CHAR_ASPECT
    scale = min(self.width, effective_height) * 0.45

    screen_x = int(self.width / 2 + (x * scale) / z_offset)
    screen_y = int(self.height / 2 - (y * scale) / (z_offset * Shape3DRenderer.CHAR_ASPECT))

    return screen_x, screen_y, 1.0 / z_offset


def _draw_thick_point(
    self,
    output: list[list[tuple[str, float]]],
    x: int,
    y: int,
    depth: float,
    color_depth: float,
) -> None:
    """Draw a point with thickness (fills adjacent cells for denser look)."""
    # Draw main point and adjacent points for thickness
    offsets = [(0, 0), (1, 0), (-1, 0), (0, 1)]  # Main + 3 adjacent
    for ox, oy in offsets:
        px, py = x + ox, y + oy
        if 0 <= px < self.width and 0 <= py < self.height:
            if output[py][px][1] < depth:
                output[py][px] = (Shape3DRenderer.EDGE_CHAR, color_depth)


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
    """Draw a thick line between two points using Bresenham's algorithm."""
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    total_dist = max(dx, dy, 1)
    step_count = 0
    x, y = x0, y0

    while True:
        t = step_count / total_dist if total_dist > 0 else 0
        depth = depth0 * (1 - t) + depth1 * t
        color_depth = depth + edge_index * 0.01

        # Draw thick point (main + adjacent cells)
        self._draw_thick_point(output, x, y, depth, color_depth)

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
    """Render one frame of the spinning shape."""
    output = [[(" ", 0.0) for _ in range(self.width)] for _ in range(self.height)]

    projected = []
    for vx, vy, vz in self._vertices:
        rx, ry, rz = self._rotate_point(vx, vy, vz)
        sx, sy, depth = self._project_point(rx, ry, rz)
        projected.append((sx, sy, depth))

    for edge_idx, (v0, v1) in enumerate(self._edges):
        x0, y0, d0 = projected[v0]
        x1, y1, d1 = projected[v1]
        self._draw_line(output, x0, y0, d0, x1, y1, d1, edge_idx)

    return output


def step(self) -> None:
    """Advance animation by one frame."""
    self.angle_x += self._speed_x
    self.angle_y += self._speed_y
    self.angle_z += self._speed_z


# Attach methods to base class
Shape3DRenderer._rotate_point = _rotate_point
Shape3DRenderer._project_point = _project_point
Shape3DRenderer._draw_thick_point = _draw_thick_point
Shape3DRenderer._draw_line = _draw_line
Shape3DRenderer.render_frame = render_frame
Shape3DRenderer.step = step


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

        # Initialize the spinning 3D shape renderers (pyramid, cube, octahedron)
        # Sizes will be recalculated dynamically based on terminal dimensions
        self._pyramid = PyramidRenderer(width=20, height=12)
        self._cube = CubeRenderer(width=20, height=12)
        self._octahedron = OctahedronRenderer(width=20, height=12)
        self._shapes = [self._pyramid, self._cube, self._octahedron]
        self._last_shape_size: tuple[int, int] = (20, 12)

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
        """Advance gradient wave and shape rotation animations."""
        if self._is_fading:
            return
        # Shift gradient offset (5 degrees per frame = full cycle in ~3.6s)
        self.gradient_offset = (self.gradient_offset + 5) % 360
        # Advance all shape rotations
        for shape in self._shapes:
            shape.step()

    def _calculate_shape_size(self) -> tuple[int, int]:
        """Calculate dynamic size for each shape based on terminal dimensions.

        Three shapes spread horizontally, each gets 1/3 of available width.

        Returns:
            Tuple of (width, height) for each shape renderer
        """
        # Get available space
        term_width = self.size.width if self.size.width > 0 else 100
        term_height = self.size.height if self.size.height > 0 else 30

        # Three shapes side by side - each gets ~1/3 of width with gaps
        available_width = term_width - 16  # Reserve for borders/padding
        shape_width = max(18, min(35, int(available_width / 3.5)))

        # Height for horizontal look
        shape_height = max(10, min(16, int(shape_width / 1.8)))

        # Reserve space for text lines below
        max_height = max(8, term_height - 10)
        shape_height = min(shape_height, max_height)

        return (shape_width, shape_height)

    # Keep old method name for compatibility with tests
    def _calculate_cube_size(self) -> tuple[int, int]:
        """Alias for _calculate_shape_size for test compatibility."""
        return self._calculate_shape_size()

    def _update_cube_size(self) -> None:
        """Update all shape renderer sizes if terminal dimensions changed."""
        new_size = self._calculate_shape_size()
        if new_size != self._last_shape_size:
            for shape in self._shapes:
                shape.width, shape.height = new_size
            self._last_shape_size = new_size

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

    def _render_shapes(self) -> Text:
        """Render all three spinning shapes side by side with rainbow gradient coloring.

        Returns:
            Rich Text object containing the colored ASCII shapes (pyramid, cube, octahedron)
        """
        # Render all shape frames
        frames = [shape.render_frame() for shape in self._shapes]
        shape_height = self._shapes[0].height
        gap = "   "  # Gap between shapes

        result = Text()

        for row_idx in range(shape_height):
            if row_idx > 0:
                result.append("\n")

            # Render each shape's row, joined by gaps
            for shape_idx, frame in enumerate(frames):
                if shape_idx > 0:
                    result.append(gap)

                row = frame[row_idx]
                # Hue offset for each shape (spread across rainbow)
                shape_hue_offset = shape_idx * 120  # 0, 120, 240 degrees

                for col_idx, (char, depth) in enumerate(row):
                    if char != " ":
                        # Color based on depth and gradient offset for flowing rainbow effect
                        hue = (
                            depth * 800
                            + col_idx * 6
                            + row_idx * 10
                            + shape_hue_offset
                            + self.gradient_offset
                        ) % 360

                        # Apply fade by reducing saturation and lightness
                        saturation = 0.85 * self.fade_progress
                        lightness = 0.55 * self.fade_progress + 0.1 * (1 - self.fade_progress)

                        color_code = hsl_to_ansi256(hue, saturation, lightness)
                        result.append(char, style=f"color({color_code})")
                    else:
                        result.append(char)

        return result

    # Keep old method name for compatibility
    def _render_cube(self) -> Text:
        """Alias for _render_shapes for compatibility."""
        return self._render_shapes()

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
        shapes = self._render_shapes()
        welcome_text = self._render_welcome_text()

        # Stack vertically: shapes on top, horizontal text bar below
        content = Group(
            Align.center(shapes),
            Text(""),  # Spacer
            Align.center(welcome_text),
        )

        # Calculate vertical padding to center the panel
        term_height = self.size.height if self.size.height > 0 else 30
        content_height = self._shapes[0].height + len(self._content_lines) + 4
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
