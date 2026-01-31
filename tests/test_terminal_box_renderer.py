"""Tests for TerminalBoxRenderer."""
from swecli.ui_textual.widgets.terminal_box_renderer import TerminalBoxRenderer


def test_normalize_line():
    """Test normalize_line utility."""
    renderer = TerminalBoxRenderer()

    # Test tab expansion
    assert renderer.normalize_line("col1\tcol2") == "col1    col2"

    # Test ANSI stripping
    ansi_text = "\x1b[31mError\x1b[0m message"
    assert renderer.normalize_line(ansi_text) == "Error message"
