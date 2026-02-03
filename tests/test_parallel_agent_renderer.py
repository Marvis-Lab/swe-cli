import sys
from rich.text import Text
from swecli.ui_textual.widgets.conversation.renderers.parallel_agent_renderer import ParallelAgentRenderer
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager

class MockLog:
    """Mock log that tracks writes for testing."""

    def __init__(self):
        self.writes = []
        self.lines = []
        self._pending_spacing_line = None

    def write(self, *args, **kwargs):
        self.writes.append(args)
        # Add to lines for line_number tracking
        self.lines.append(args[0] if args else "")

    def set_timer(self, *args):
        return None

    def refresh_line(self, *args):
        pass

    def refresh(self):
        pass

    @property
    def virtual_size(self):
        class Size:
            width = 100

        return Size()

    def scroll_end(self, animate=False):
        pass

def test_parallel_agent_renderer_lifecycle():
    log = MockLog()
    spacing = SpacingManager(log)
    renderer = ParallelAgentRenderer(log, spacing)

    assert renderer.parallel_group is None

    agent_infos = [
        {"agent_type": "Agent1", "description": "Desc1", "tool_call_id": "id1"},
        {"agent_type": "Agent2", "description": "Desc2", "tool_call_id": "id2"},
    ]

    # Start
    renderer.on_parallel_agents_start(agent_infos)

    assert renderer.parallel_group is not None
    assert len(renderer.parallel_group.agents) == 2
    assert renderer.has_active_parallel_group() is True

    # Complete one agent
    renderer.on_parallel_agent_complete("id1", success=True)
    assert renderer.parallel_group.agents["id1"].status == "completed"

    # Done
    renderer.on_parallel_agents_done()
    assert renderer.has_active_parallel_group() is False
    assert renderer.parallel_group is None
    print("✅ ParallelAgentRenderer lifecycle test passed")

if __name__ == "__main__":
    test_parallel_agent_renderer_lifecycle()
