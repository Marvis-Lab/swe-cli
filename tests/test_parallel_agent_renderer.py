#!/usr/bin/env python
"""Unit tests for ParallelAgentRenderer."""
import sys
from rich.text import Text
from swecli.ui_textual.widgets.conversation.renderers.parallel_agent_renderer import ParallelAgentRenderer
from swecli.ui_textual.widgets.conversation.renderers.models import ParallelAgentGroup, AgentInfo

class MockLog:
    def __init__(self):
        self.writes = []
        self.lines = []

    def write(self, *args, **kwargs):
        self.writes.append(args)
        self.lines.append(args[0] if args else "")

    def refresh_line(self, *args): pass

class MockSpacing:
    def before_parallel_agents(self): pass
    def after_parallel_agents(self): pass

def test_parallel_agent_lifecycle():
    log = MockLog()
    renderer = ParallelAgentRenderer(log, MockSpacing())

    assert not renderer.has_active_group()

    agent_infos = [{"agent_type": "Test", "tool_call_id": "1", "description": "Desc"}]
    renderer.start(agent_infos)

    assert renderer.has_active_group()
    assert renderer.parallel_group is not None
    assert "1" in renderer.parallel_group.agents

    # Check lines written (Header, Agent, Status)
    assert len(log.lines) == 3

    # Test update tool call
    should_render = renderer.update_tool_call("1", Text("some_tool"))
    assert should_render is False # Default collapsed
    assert renderer.parallel_group.agents["1"].tool_count == 1

    # Test complete agent
    renderer.complete_agent("1", True)
    assert renderer.parallel_group.agents["1"].status == "completed"

    # Test done
    renderer.done()
    assert renderer.parallel_group is None
    assert not renderer.has_active_group()

def test_expansion_toggle():
    log = MockLog()
    renderer = ParallelAgentRenderer(log, MockSpacing())

    assert renderer.expanded is False
    renderer.toggle_expansion()
    assert renderer.expanded is True

    renderer.start([{"agent_type": "Test"}])
    assert renderer.parallel_group.expanded is True

    # update_tool_call should return True now
    should_render = renderer.update_tool_call("agent_0", "tool")
    assert should_render is True

if __name__ == "__main__":
    test_parallel_agent_lifecycle()
    test_expansion_toggle()
    print("ParallelAgentRenderer tests passed")
