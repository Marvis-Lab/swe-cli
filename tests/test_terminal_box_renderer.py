"""Tests for TerminalBoxRenderer."""
import os
from unittest.mock import Mock
from rich.text import Text

from swecli.ui_textual.widgets.terminal_box_renderer import TerminalBoxRenderer, TerminalBoxConfig


def test_format_path():
    """Test format_path utility."""
    renderer = TerminalBoxRenderer()

    # Setup paths
    home = os.path.expanduser("~")
    path_in_home = os.path.join(home, "projects", "swecli")
    path_outside = "/usr/bin/python"

    # Test home replacement
    assert renderer.format_path(path_in_home) == "~/projects/swecli"

    # Test path outside home
    assert renderer.format_path(path_outside) == "/usr/bin/python"


def test_normalize_line():
    """Test normalize_line utility."""
    renderer = TerminalBoxRenderer()

    # Test tab expansion
    assert renderer.normalize_line("col1\tcol2") == "col1    col2"

    # Test ANSI stripping
    ansi_text = "\x1b[31mError\x1b[0m message"
    assert renderer.normalize_line(ansi_text) == "Error message"


