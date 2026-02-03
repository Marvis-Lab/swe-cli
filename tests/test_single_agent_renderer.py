import sys
from rich.text import Text
from swecli.ui_textual.widgets.conversation.renderers.single_agent_renderer import SingleAgentRenderer
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager

class MockLog:
    """Mock log that tracks writes for testing."""

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

    def refresh(self):
        pass

    @property
    def virtual_size(self):
        class Size:
            width = 100
        return Size()

    def scroll_end(self, animate=False):
        pass

def test_single_agent_renderer_lifecycle():
    log = MockLog()
    spacing = SpacingManager(log)
    renderer = SingleAgentRenderer(log, spacing)

    assert renderer.single_agent is None

    # Start
    renderer.on_single_agent_start("Explore", "Search code", "tool_1")

    assert renderer.single_agent is not None
    assert renderer.single_agent.agent_type == "Explore"
    assert renderer.single_agent.status == "running"

    # Complete
    renderer.on_single_agent_complete("tool_1", success=True)
    assert renderer.single_agent is None
    print("✅ SingleAgentRenderer lifecycle test passed")

if __name__ == "__main__":
    test_single_agent_renderer_lifecycle()
