#!/usr/bin/env python
import unittest
from rich.text import Text
from swecli.ui_textual.widgets.conversation.renderers.nested_tool_renderer import NestedToolRenderer

class MockLog:
    def __init__(self):
        self.writes = []
        self.lines = []
        self._pending_spacing_line = None

    def write(self, *args, **kwargs):
        self.writes.append(args)
        self.lines.append(args[0] if args else "")

    def refresh_line(self, *args):
        pass

class MockSpacingManager:
    def before_nested_tool_call(self): pass

class TestNestedToolRenderer(unittest.TestCase):
    def setUp(self):
        self.log = MockLog()
        self.spacing = MockSpacingManager()
        self.renderer = NestedToolRenderer(self.log, self.spacing)

    def test_add_tool(self):
        self.renderer.add_tool(Text("ls"), 1, "parent", "tool_1")
        self.assertTrue(self.renderer.has_active_tools())
        self.assertIn(("parent", "tool_1"), self.renderer.tools)

    def test_complete_tool(self):
        self.renderer.add_tool(Text("ls"), 1, "parent", "tool_1")
        self.renderer.complete_tool("ls", 1, "parent", True, "tool_1")
        self.assertFalse(self.renderer.has_active_tools())

if __name__ == "__main__":
    unittest.main()
