#!/usr/bin/env python
"""Unit tests for NestedToolRenderer."""
import sys
from rich.text import Text
from swecli.ui_textual.widgets.conversation.renderers.nested_tool_renderer import NestedToolRenderer

class MockLog:
    def __init__(self):
        self.writes = []
        self.lines = []

    def write(self, *args, **kwargs):
        self.writes.append(args)
        self.lines.append(args[0] if args else "")

    def refresh_line(self, *args): pass

class MockSpacing:
    def before_nested_tool_call(self): pass

def test_nested_tool_lifecycle():
    log = MockLog()
    renderer = NestedToolRenderer(log, MockSpacing())

    assert not renderer.has_active_tools()

    renderer.add_nested_tool_call("ls -la", depth=1, parent="p1", tool_id="t1")

    assert renderer.has_active_tools()
    assert ("p1", "t1") in renderer._nested_tools

    renderer.complete_nested_tool_call("ls", 1, "p1", True, "t1")

    assert not renderer.has_active_tools()
    assert ("p1", "t1") not in renderer._nested_tools

def test_legacy_nested_tool():
    log = MockLog()
    renderer = NestedToolRenderer(log, MockSpacing())

    # Simulate legacy add (no tool_id)
    renderer.add_nested_tool_call("ls -la", depth=1, parent="p1")

    # Should use legacy tracking
    assert renderer.has_active_tools()
    assert renderer._nested_tool_line is not None

    # Complete
    renderer.complete_nested_tool_call("ls", 1, "p1", True)

    assert not renderer.has_active_tools()
    assert renderer._nested_tool_line is None

if __name__ == "__main__":
    test_nested_tool_lifecycle()
    test_legacy_nested_tool()
    print("NestedToolRenderer tests passed")
