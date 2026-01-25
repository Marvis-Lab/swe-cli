"""Tests for AnimatedWelcomePanel widget and DonutRenderer."""


from swecli.ui_textual.widgets.welcome_panel import (
    AnimatedWelcomePanel,
    DonutRenderer,
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
        # Check mode appears in content
        assert any("PLAN" in line for line in panel._content_lines)

    def test_creation_with_username(self):
        """Panel shows username in greeting."""
        panel = AnimatedWelcomePanel(username="TestUser")
        assert panel._username == "TestUser"
        assert any("TestUser" in line for line in panel._content_lines)

    def test_content_generation(self):
        """Content lines are generated correctly."""
        panel = AnimatedWelcomePanel()
        lines = panel._content_lines

        # Check for expected content
        assert len(lines) > 0
        assert any("SWE-CLI" in line for line in lines)
        assert any("/help" in line for line in lines)
        assert any("Shift+Tab" in line for line in lines)

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


class TestDonutRenderer:
    """Test DonutRenderer spinning 3D ASCII torus."""

    def test_creation_default(self):
        """DonutRenderer can be created with defaults."""
        donut = DonutRenderer()
        assert donut.width == 30
        assert donut.height == 15
        assert donut.A != 0.0  # Initial rotation for 3D view
        assert donut.B != 0.0

    def test_creation_custom_size(self):
        """DonutRenderer respects custom dimensions."""
        donut = DonutRenderer(width=40, height=20)
        assert donut.width == 40
        assert donut.height == 20

    def test_render_frame_dimensions(self):
        """render_frame returns correct grid dimensions."""
        donut = DonutRenderer(width=25, height=12)
        frame = donut.render_frame()

        assert len(frame) == 12  # height
        assert all(len(row) == 25 for row in frame)  # width

    def test_render_frame_produces_characters(self):
        """render_frame produces donut characters (not all spaces)."""
        donut = DonutRenderer()
        frame = donut.render_frame()

        # Count non-space characters
        char_count = sum(1 for row in frame for char, _ in row if char != " ")
        assert char_count > 50, "Donut should have visible characters"

    def test_render_frame_uses_luminance_chars(self):
        """render_frame uses the correct luminance character set."""
        donut = DonutRenderer()
        frame = donut.render_frame()

        # All characters should be from the CHARS set or space
        valid_chars = set(donut.CHARS + " ")
        for row in frame:
            for char, _ in row:
                assert char in valid_chars, f"Invalid character: {char}"

    def test_render_frame_includes_depth(self):
        """render_frame returns depth values for each cell."""
        donut = DonutRenderer()
        frame = donut.render_frame()

        # Check that visible characters have positive depth
        for row in frame:
            for char, depth in row:
                if char != " ":
                    assert depth > 0, "Visible characters should have positive depth"
                else:
                    assert depth == 0.0, "Empty cells should have zero depth"

    def test_step_advances_rotation(self):
        """step() advances the rotation angles."""
        donut = DonutRenderer()
        initial_A = donut.A
        initial_B = donut.B

        donut.step()

        assert donut.A > initial_A
        assert donut.B > initial_B

    def test_step_rotation_increments(self):
        """step() uses expected rotation increments."""
        donut = DonutRenderer()
        initial_A = donut.A
        initial_B = donut.B

        donut.step()

        assert donut.A == initial_A + 0.04
        assert donut.B == initial_B + 0.02

    def test_multiple_steps_produce_different_frames(self):
        """Animation steps produce visually different frames."""
        donut = DonutRenderer()

        frame1 = donut.render_frame()
        donut.step()
        donut.step()
        donut.step()
        frame2 = donut.render_frame()

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

    def test_luminance_characters_ordering(self):
        """CHARS are ordered from dark to bright."""
        donut = DonutRenderer()
        # The characters should progress from less dense to more dense
        assert donut.CHARS == ".,-~:;=!*#$@"


class TestAnimatedWelcomePanelWithDonut:
    """Test AnimatedWelcomePanel donut integration."""

    def test_panel_has_donut_renderer(self):
        """Panel creates a DonutRenderer instance."""
        panel = AnimatedWelcomePanel()
        assert hasattr(panel, "_donut")
        assert isinstance(panel._donut, DonutRenderer)

    def test_render_donut_method_exists(self):
        """Panel has _render_donut method."""
        panel = AnimatedWelcomePanel()
        assert hasattr(panel, "_render_donut")
        assert callable(panel._render_donut)

    def test_render_donut_produces_text(self):
        """_render_donut produces Rich Text with content."""
        panel = AnimatedWelcomePanel()
        donut_text = panel._render_donut()

        from rich.text import Text

        assert isinstance(donut_text, Text)
        assert len(donut_text.plain) > 0

    def test_render_welcome_text_method_exists(self):
        """Panel has _render_welcome_text method."""
        panel = AnimatedWelcomePanel()
        assert hasattr(panel, "_render_welcome_text")
        assert callable(panel._render_welcome_text)

    def test_update_gradient_steps_donut(self):
        """_update_gradient advances the donut animation."""
        panel = AnimatedWelcomePanel()
        initial_A = panel._donut.A

        panel._update_gradient()

        assert panel._donut.A > initial_A


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

    def test_donut_renderer_exported(self):
        """DonutRenderer is exported from module."""
        from swecli.ui_textual.widgets.welcome_panel import DonutRenderer as Imported

        assert Imported is DonutRenderer
