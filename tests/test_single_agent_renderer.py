#!/usr/bin/env python
"""Unit tests for SingleAgentRenderer."""
import sys
from rich.text import Text
from swecli.ui_textual.widgets.conversation.renderers.single_agent_renderer import SingleAgentRenderer

class MockLog:
    def __init__(self):
        self.writes = []
        self.lines = []

    def write(self, *args, **kwargs):
        self.writes.append(args)
        self.lines.append(args[0] if args else "")

    def refresh_line(self, *args): pass

class MockSpacing:
    def before_single_agent(self): pass
    def after_single_agent(self): pass

def test_single_agent_lifecycle():
    log = MockLog()
    renderer = SingleAgentRenderer(log, MockSpacing())

    assert not renderer.has_active_agent()

    renderer.start("Explorer", "Exploring...", "id_1")

    assert renderer.has_active_agent()
    assert renderer.single_agent is not None
    assert renderer.single_agent.tool_call_id == "id_1"

    # Check lines written (Header, Status, Tool)
    assert len(log.lines) == 3

    # Test update tool call
    should_render = renderer.update_tool_call(Text("some_tool"))
    assert should_render is False # Always false for single agent (collapsed nested)
    assert renderer.single_agent.tool_count == 1
    assert "some_tool" in renderer.single_agent.current_tool

    # Test complete
    renderer.complete("id_1", True)
    assert renderer.single_agent is None
    assert not renderer.has_active_agent()

if __name__ == "__main__":
    test_single_agent_lifecycle()
    print("SingleAgentRenderer tests passed")
