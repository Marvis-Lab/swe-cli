import pytest
from rich.text import Text
from swecli.ui_textual.widgets.conversation.renderers.parallel_agent_renderer import ParallelAgentRenderer

class MockLog:
    def __init__(self):
        self.lines = []
        self.writes = []

    def write(self, text, **kwargs):
        self.writes.append(text)
        # In real log, writing appends to lines.
        # Here we just track writes.
        # But renderer relies on len(self.log.lines).
        # We need to simulate lines growth.
        # text is Rich Text.
        self.lines.append(text)

    def refresh_line(self, index):
        pass

    @property
    def virtual_size(self):
        class Size:
            width = 80
        return Size()

class MockSpacingManager:
    def before_parallel_agents(self):
        pass
    def after_parallel_agents(self):
        pass

def test_parallel_renderer_lifecycle():
    log = MockLog()
    spacing = MockSpacingManager()
    renderer = ParallelAgentRenderer(log, spacing)

    assert not renderer.is_active

    agent_infos = [
        {"agent_type": "Explore", "description": "Explore docs", "tool_call_id": "call_1"},
    ]
    renderer.on_start(agent_infos)

    assert renderer.is_active
    assert renderer.group is not None
    assert "call_1" in renderer.group.agents

    # Verify initial writes: Header, Agent Row, Status Row
    assert len(log.lines) == 3

    # Complete agent
    renderer.on_complete("call_1", success=True)
    assert renderer.group.agents["call_1"].status == "completed"

    # All done
    renderer.on_all_done()
    assert not renderer.is_active
    assert renderer.group is None

def test_parallel_renderer_update_tool():
    log = MockLog()
    spacing = MockSpacingManager()
    renderer = ParallelAgentRenderer(log, spacing)

    agent_infos = [
        {"agent_type": "Explore", "description": "Desc", "tool_call_id": "call_1"},
    ]
    renderer.on_start(agent_infos)

    renderer.update_agent_tool("call_1", "ls -la")
    agent = renderer.group.agents["call_1"]
    assert agent.tool_count == 1
    assert agent.current_tool == "ls -la"

def test_parallel_renderer_animate():
    log = MockLog()
    spacing = MockSpacingManager()
    renderer = ParallelAgentRenderer(log, spacing)

    agent_infos = [
        {"agent_type": "Explore", "description": "Desc", "tool_call_id": "call_1"},
    ]
    renderer.on_start(agent_infos)

    initial_idx = renderer.header_spinner_index
    renderer.animate()
    assert renderer.header_spinner_index == initial_idx + 1
