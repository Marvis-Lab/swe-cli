#!/usr/bin/env python
import unittest
from swecli.ui_textual.widgets.conversation.renderers.single_agent_renderer import SingleAgentRenderer

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
    def before_single_agent(self): pass
    def after_single_agent(self): pass

class TestSingleAgentRenderer(unittest.TestCase):
    def setUp(self):
        self.log = MockLog()
        self.spacing = MockSpacingManager()
        self.renderer = SingleAgentRenderer(self.log, self.spacing)

    def test_start_creates_agent(self):
        self.renderer.start("Agent", "Description", "call_1")
        self.assertIsNotNone(self.renderer.agent)
        self.assertEqual(self.renderer.agent.tool_call_id, "call_1")

    def test_update_tool(self):
        self.renderer.start("Agent", "Description", "call_1")
        self.renderer.update_tool("ls")
        self.assertEqual(self.renderer.agent.current_tool, "ls")
        self.assertEqual(self.renderer.agent.tool_count, 1)

    def test_complete_clears_agent(self):
        self.renderer.start("Agent", "Description", "call_1")
        self.renderer.complete("call_1", True)
        self.assertIsNone(self.renderer.agent)

if __name__ == "__main__":
    unittest.main()
