import pytest
from rich.text import Text
from swecli.ui_textual.widgets.conversation.renderers.nested_tool_renderer import NestedToolRenderer

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
    def before_nested_tool_call(self):
        pass

def test_nested_tool_renderer_lifecycle():
    log = MockLog()
    spacing = MockSpacingManager()
    renderer = NestedToolRenderer(log, spacing)

    assert not renderer.has_active_tools

    renderer.add_tool(Text("read_file"), depth=1, parent="parent_1", tool_id="tool_1")

    assert renderer.has_active_tools
    assert ("parent_1", "tool_1") in renderer.nested_tools

    # Verify write
    assert len(log.lines) == 1

    renderer.complete_tool("read_file", depth=1, parent="parent_1", success=True, tool_id="tool_1")

    # Should remove from nested tools but keep line in log (updated)
    assert ("parent_1", "tool_1") not in renderer.nested_tools
    assert not renderer.has_active_tools
    assert len(log.lines) == 1

def test_nested_tool_renderer_animate():
    log = MockLog()
    spacing = MockSpacingManager()
    renderer = NestedToolRenderer(log, spacing)

    renderer.add_tool(Text("read_file"), depth=1, parent="parent_1", tool_id="tool_1")

    state = renderer.nested_tools[("parent_1", "tool_1")]
    initial_color = state.color_index

    renderer.animate()

    state = renderer.nested_tools[("parent_1", "tool_1")]
    assert state.color_index == initial_color + 1
