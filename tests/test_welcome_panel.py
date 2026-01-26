"""Tests for AnimatedWelcomePanel widget and CubeRenderer."""

from swecli.ui_textual.widgets.welcome_panel import (
    AnimatedWelcomePanel,
    CubeRenderer,
    hsl_to_ansi256,
)
from swecli.core.runtime import OperationMode


class TestHslToAnsi256:
    """Test HSL to ANSI-256 color conversion."""

    def test_red_hue(self):
        """Red (hue=0) should produce a red-ish color."""
        color = hsl_to_ansi256(0, 0.8, 0.6)
        assert 16 <= color <= 231  # Color cube range

    def test_green_hue(self):
        """Green (hue=120) should produce a green-ish color."""
        color = hsl_to_ansi256(120, 0.8, 0.6)
        assert 16 <= color <= 231

    def test_blue_hue(self):
        """Blue (hue=240) should produce a blue-ish color."""
        color = hsl_to_ansi256(240, 0.8, 0.6)
        assert 16 <= color <= 231

    def test_hue_wrapping(self):
        """Hue should wrap around at 360."""
        color_0 = hsl_to_ansi256(0, 0.7, 0.6)
        color_360 = hsl_to_ansi256(360, 0.7, 0.6)
        assert color_0 == color_360

    def test_full_rainbow(self):
        """All rainbow hues should produce valid colors."""
        for hue in range(0, 360, 30):
            color = hsl_to_ansi256(hue)
            assert 16 <= color <= 231, f"Hue {hue} produced invalid color {color}"


class TestAnimatedWelcomePanel:
    """Test AnimatedWelcomePanel widget."""

    def test_creation_default(self):
        """Panel can be created with defaults."""
        panel = AnimatedWelcomePanel()
        assert panel is not None
        assert panel._current_mode == OperationMode.NORMAL
        assert panel._username is not None

    def test_creation_with_mode(self):
        """Panel respects operation mode."""
        panel = AnimatedWelcomePanel(current_mode=OperationMode.PLAN)
        assert panel._current_mode == OperationMode.PLAN
        # Check mode appears in content (multi-line list)
        content_text = "\n".join(panel._content_lines)
        assert "PLAN" in content_text

    def test_creation_with_username(self):
        """Panel stores username (no longer shown in horizontal bar)."""
        panel = AnimatedWelcomePanel(username="TestUser")
        assert panel._username == "TestUser"
        # Username is stored but not shown in the compact horizontal bar

    def test_content_generation(self):
        """Content is generated as multi-line list."""
        panel = AnimatedWelcomePanel()
        content = panel._content_lines

        # Check for expected content in multi-line format
        assert isinstance(content, list)
        assert len(content) > 0
        content_text = "\n".join(content)
        assert "S W E - C L I" in content_text  # ASCII art title with spaces
        assert "/help" in content_text
        assert "Shift+Tab" in content_text

    def test_gradient_offset_reactive(self):
        """Gradient offset is reactive property."""
        panel = AnimatedWelcomePanel()
        assert panel.gradient_offset == 0

        panel.gradient_offset = 180
        assert panel.gradient_offset == 180

    def test_fade_progress_reactive(self):
        """Fade progress is reactive property."""
        panel = AnimatedWelcomePanel()
        assert panel.fade_progress == 1.0

        panel.fade_progress = 0.5
        assert panel.fade_progress == 0.5

    def test_apply_gradient_preserves_whitespace(self):
        """Gradient coloring preserves whitespace."""
        panel = AnimatedWelcomePanel()
        text = "  hello  world  "
        result = panel._apply_gradient(text)

        # Result should have same length (Rich Text)
        assert len(result.plain) == len(text)

    def test_apply_gradient_colors_characters(self):
        """Gradient applies colors to non-whitespace."""
        panel = AnimatedWelcomePanel()
        text = "abc"
        result = panel._apply_gradient(text)

        # Should produce Rich Text with style spans
        assert result.plain == "abc"
        # Each character should have a style
        spans = result._spans
        assert len(spans) >= 1

    def test_fade_out_initial_state(self):
        """Panel starts with fading disabled."""
        panel = AnimatedWelcomePanel()
        assert not panel._is_fading
        assert panel.fade_progress == 1.0

    def test_do_fade_decrements_progress(self):
        """_do_fade decrements fade_progress."""
        panel = AnimatedWelcomePanel()
        panel._is_fading = True
        initial = panel.fade_progress

        panel._do_fade()
        assert panel.fade_progress < initial

    def test_get_version(self):
        """Version retrieval works."""
        version = AnimatedWelcomePanel.get_version()
        assert version.startswith("v")


class TestCubeRenderer:
    """Test CubeRenderer spinning 3D wireframe cube."""

    def test_creation_default(self):
        """CubeRenderer can be created with defaults."""
        cube = CubeRenderer()
        assert cube.width == 35
        assert cube.height == 18
        assert cube.angle_x != 0.0  # Initial rotation for 3D view
        assert cube.angle_y != 0.0

    def test_creation_custom_size(self):
        """CubeRenderer respects custom dimensions."""
        cube = CubeRenderer(width=40, height=20)
        assert cube.width == 40
        assert cube.height == 20

    def test_render_frame_dimensions(self):
        """render_frame returns correct grid dimensions."""
        cube = CubeRenderer(width=25, height=12)
        frame = cube.render_frame()

        assert len(frame) == 12  # height
        assert all(len(row) == 25 for row in frame)  # width

    def test_render_frame_produces_characters(self):
        """render_frame produces cube characters (not all spaces)."""
        cube = CubeRenderer()
        frame = cube.render_frame()

        # Count non-space characters
        char_count = sum(1 for row in frame for char, _ in row if char != " ")
        assert char_count > 20, "Cube should have visible characters"

    def test_render_frame_uses_edge_char(self):
        """render_frame uses the correct edge character."""
        cube = CubeRenderer()
        frame = cube.render_frame()

        # All characters should be EDGE_CHAR or space
        valid_chars = {cube.EDGE_CHAR, " "}
        for row in frame:
            for char, _ in row:
                assert char in valid_chars, f"Invalid character: {char}"

    def test_render_frame_includes_depth(self):
        """render_frame returns depth values for each cell."""
        cube = CubeRenderer()
        frame = cube.render_frame()

        # Check that visible characters have positive depth
        for row in frame:
            for char, depth in row:
                if char != " ":
                    assert depth > 0, "Visible characters should have positive depth"
                else:
                    assert depth == 0.0, "Empty cells should have zero depth"

    def test_step_advances_rotation(self):
        """step() advances the rotation angles."""
        cube = CubeRenderer()
        initial_x = cube.angle_x
        initial_y = cube.angle_y
        initial_z = cube.angle_z

        cube.step()

        assert cube.angle_x > initial_x
        assert cube.angle_y > initial_y
        assert cube.angle_z > initial_z

    def test_step_rotation_increments(self):
        """step() uses expected rotation increments."""
        cube = CubeRenderer()
        initial_x = cube.angle_x
        initial_y = cube.angle_y
        initial_z = cube.angle_z

        cube.step()

        assert cube.angle_x == initial_x + 0.03
        assert cube.angle_y == initial_y + 0.04
        assert cube.angle_z == initial_z + 0.01

    def test_multiple_steps_produce_different_frames(self):
        """Animation steps produce visually different frames."""
        cube = CubeRenderer()

        frame1 = cube.render_frame()
        cube.step()
        cube.step()
        cube.step()
        frame2 = cube.render_frame()

        # Compare character positions - should be different
        chars1 = [
            (r, c, char)
            for r, row in enumerate(frame1)
            for c, (char, _) in enumerate(row)
            if char != " "
        ]
        chars2 = [
            (r, c, char)
            for r, row in enumerate(frame2)
            for c, (char, _) in enumerate(row)
            if char != " "
        ]

        assert chars1 != chars2, "Frames after animation should differ"

    def test_has_vertices_and_edges(self):
        """CubeRenderer has 8 vertices and 12 edges."""
        cube = CubeRenderer()
        assert len(cube._vertices) == 8, "Cube should have 8 vertices"
        assert len(cube._edges) == 12, "Cube should have 12 edges"


class TestAnimatedWelcomePanelWithCube:
    """Test AnimatedWelcomePanel cube integration."""

    def test_panel_has_cube_renderer(self):
        """Panel creates a CubeRenderer instance."""
        panel = AnimatedWelcomePanel()
        assert hasattr(panel, "_cube")
        assert isinstance(panel._cube, CubeRenderer)

    def test_calculate_cube_size_small_terminal(self):
        """Cube size adapts to small terminal."""
        panel = AnimatedWelcomePanel()

        # Mock small terminal size
        class MockSize:
            width = 80
            height = 24

        panel._size = MockSize()
        original_size = type(panel).size
        type(panel).size = property(lambda self: self._size)

        try:
            width, height = panel._calculate_cube_size()
            assert width >= 40  # Wide horizontal cube
            assert height >= 8  # Short height for horizontal style
            assert height <= 14  # Not too tall
        finally:
            type(panel).size = original_size

    def test_calculate_cube_size_large_terminal(self):
        """Cube size grows with large terminal."""
        panel = AnimatedWelcomePanel()

        # Mock large terminal size
        class MockSize:
            width = 160
            height = 50

        panel._size = MockSize()
        original_size = type(panel).size
        type(panel).size = property(lambda self: self._size)

        try:
            width, height = panel._calculate_cube_size()
            assert width >= 70  # Wide horizontal cube
            assert height >= 10  # Short but reasonable height
            assert height <= 14  # Capped for horizontal style
        finally:
            type(panel).size = original_size

    def test_update_cube_size_changes_renderer(self):
        """_update_cube_size updates the renderer dimensions."""
        panel = AnimatedWelcomePanel()

        # Mock a specific terminal size
        class MockSize:
            width = 120
            height = 40

        panel._size = MockSize()
        original_size = type(panel).size
        type(panel).size = property(lambda self: self._size)

        try:
            panel._update_cube_size()
            # Verify cube dimensions were updated
            expected_size = panel._calculate_cube_size()
            assert panel._cube.width == expected_size[0]
            assert panel._cube.height == expected_size[1]
        finally:
            type(panel).size = original_size

    def test_render_cube_method_exists(self):
        """Panel has _render_cube method."""
        panel = AnimatedWelcomePanel()
        assert hasattr(panel, "_render_cube")
        assert callable(panel._render_cube)

    def test_render_cube_produces_text(self):
        """_render_cube produces Rich Text with content."""
        panel = AnimatedWelcomePanel()
        cube_text = panel._render_cube()

        from rich.text import Text

        assert isinstance(cube_text, Text)
        assert len(cube_text.plain) > 0

    def test_render_welcome_text_method_exists(self):
        """Panel has _render_welcome_text method."""
        panel = AnimatedWelcomePanel()
        assert hasattr(panel, "_render_welcome_text")
        assert callable(panel._render_welcome_text)

    def test_update_gradient_steps_cube(self):
        """_update_gradient advances the cube animation."""
        panel = AnimatedWelcomePanel()
        initial_angle = panel._cube.angle_x

        panel._update_gradient()

        assert panel._cube.angle_x > initial_angle


class TestWelcomePanelSessionResumption:
    """Test welcome panel behavior on session resumption."""

    def test_chat_app_new_session_defaults(self):
        """New session should have welcome_visible=True by default."""
        from swecli.ui_textual.chat_app import SWECLIChatApp

        app = SWECLIChatApp(is_resumed_session=False)
        assert app._is_resumed_session is False
        assert app._welcome_visible is True

    def test_chat_app_resumed_session_flags(self):
        """Resumed session should have welcome_visible=False."""
        from swecli.ui_textual.chat_app import SWECLIChatApp

        app = SWECLIChatApp(is_resumed_session=True)
        assert app._is_resumed_session is True
        assert app._welcome_visible is False

    def test_create_chat_app_accepts_resumed_flag(self):
        """create_chat_app should accept is_resumed_session parameter."""
        from swecli.ui_textual.chat_app import create_chat_app

        # New session
        app_new = create_chat_app(is_resumed_session=False)
        assert app_new._is_resumed_session is False
        assert app_new._welcome_visible is True

        # Resumed session
        app_resumed = create_chat_app(is_resumed_session=True)
        assert app_resumed._is_resumed_session is True
        assert app_resumed._welcome_visible is False


class TestAnimatedWelcomePanelIntegration:
    """Integration tests for AnimatedWelcomePanel."""

    def test_import_from_widgets(self):
        """Can import from widgets package."""
        from swecli.ui_textual.widgets import AnimatedWelcomePanel as Imported

        assert Imported is AnimatedWelcomePanel

    def test_widget_has_default_css(self):
        """Widget has CSS defined."""
        panel = AnimatedWelcomePanel()
        assert hasattr(panel, "DEFAULT_CSS")
        assert "AnimatedWelcomePanel" in panel.DEFAULT_CSS

    def test_cube_renderer_exported(self):
        """CubeRenderer is exported from module."""
        from swecli.ui_textual.widgets.welcome_panel import CubeRenderer as Imported

        assert Imported is CubeRenderer
