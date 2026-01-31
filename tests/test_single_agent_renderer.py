import pytest
from swecli.ui_textual.widgets.conversation.renderers.single_agent_renderer import SingleAgentRenderer

class MockLog:
    def __init__(self):
        self.lines = []
        self.writes = []

    def write(self, text, **kwargs):
        self.writes.append(text)
        self.lines.append(text)

    def refresh_line(self, index):
        pass

    @property
    def virtual_size(self):
        class Size:
            width = 80
        return Size()

class MockSpacingManager:
    def before_single_agent(self):
        pass
    def after_single_agent(self):
        pass

def test_single_agent_renderer_lifecycle():
    log = MockLog()
    spacing = MockSpacingManager()
    renderer = SingleAgentRenderer(log, spacing)

    assert not renderer.is_active

    renderer.on_start("Explore", "Docs", "call_1")

    assert renderer.is_active
    assert renderer.agent is not None
    assert renderer.agent.tool_call_id == "call_1"

    # Header, Status, Tool
    assert len(log.lines) == 3

    renderer.update_tool("ls")
    assert renderer.agent.tool_count == 1
    assert renderer.agent.current_tool == "ls"

    renderer.on_complete("call_1", success=True)
    assert not renderer.is_active
    assert renderer.agent is None

def test_single_agent_renderer_animate():
    log = MockLog()
    spacing = MockSpacingManager()
    renderer = SingleAgentRenderer(log, spacing)

    renderer.on_start("Explore", "Docs", "call_1")

    idx = renderer.header_spinner_index
    bullet_idx = renderer.bullet_gradient_index

    renderer.animate()

    assert renderer.header_spinner_index == idx + 1
    assert renderer.bullet_gradient_index == bullet_idx + 1
