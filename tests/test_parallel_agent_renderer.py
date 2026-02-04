#!/usr/bin/env python
import unittest
from rich.text import Text
from swecli.ui_textual.widgets.conversation.renderers.parallel_agent_renderer import ParallelAgentRenderer
from swecli.ui_textual.widgets.conversation.renderers.models import AgentInfo

class MockLog:
    def __init__(self):
        self.writes = []
        self.lines = []
        self._pending_spacing_line = None

    def write(self, *args, **kwargs):
        self.writes.append(args)
        self.lines.append(args[0] if args else "")

    def set_timer(self, *args):
        return None

    def refresh_line(self, *args):
        pass

    @property
    def virtual_size(self):
        class Size:
            width = 100
        return Size()

class MockSpacingManager:
    def before_parallel_agents(self): pass
    def after_parallel_agents(self): pass

class TestParallelAgentRenderer(unittest.TestCase):
    def setUp(self):
        self.log = MockLog()
        self.spacing = MockSpacingManager()
        self.renderer = ParallelAgentRenderer(self.log, self.spacing)

    def test_start_creates_group(self):
        agent_infos = [
            {"agent_type": "Agent", "description": "Test Agent", "tool_call_id": "call_1"}
        ]
        self.renderer.start(agent_infos)

        self.assertIsNotNone(self.renderer.group)
        self.assertIn("call_1", self.renderer.group.agents)
        self.assertEqual(len(self.renderer.group.agents), 1)

    def test_complete_agent_updates_status(self):
        agent_infos = [{"tool_call_id": "call_1"}]
        self.renderer.start(agent_infos)

        self.renderer.complete_agent("call_1", True)
        self.assertEqual(self.renderer.group.agents["call_1"].status, "completed")

    def test_done_completes_all_agents(self):
        agent_infos = [{"tool_call_id": "call_1"}, {"tool_call_id": "call_2"}]
        self.renderer.start(agent_infos)

        self.renderer.done()
        self.assertIsNone(self.renderer.group)

if __name__ == "__main__":
    unittest.main()
