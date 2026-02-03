import sys
import time
from rich.text import Text
from swecli.ui_textual.widgets.conversation.renderers.nested_tool_renderer import NestedToolRenderer
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

def test_nested_tool_renderer_lifecycle():
    log = MockLog()
    spacing = SpacingManager(log)
    renderer = NestedToolRenderer(log, spacing)

    assert not renderer.has_active_tools

    # Add tool
    tool_id = renderer.add_nested_tool_call("list_files", depth=1, parent="agent1")
    assert renderer.has_active_tools
    assert len(renderer._nested_tools) == 1

    # Complete tool
    renderer.complete_nested_tool_call("list_files", depth=1, parent="agent1", success=True, tool_id=tool_id)

    assert not renderer.has_active_tools
    assert len(renderer._nested_tools) == 0
    print("✅ NestedToolRenderer lifecycle test passed")

if __name__ == "__main__":
    test_nested_tool_renderer_lifecycle()
