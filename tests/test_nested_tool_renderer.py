import pytest
from unittest.mock import MagicMock, patch
from rich.text import Text

from swecli.ui_textual.widgets.conversation.renderers.nested_tool_renderer import NestedToolRenderer
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface
from swecli.ui_textual.widgets.conversation.spacing_manager import SpacingManager

@pytest.fixture
def mock_log():
    log = MagicMock(spec=RichLogInterface)
    log.lines = []
    log.virtual_size = MagicMock()
    log.virtual_size.width = 80
    return log

@pytest.fixture
def mock_spacing():
    return MagicMock(spec=SpacingManager)

def test_add_nested_tool_call(mock_log, mock_spacing):
    renderer = NestedToolRenderer(mock_log, mock_spacing)

    def write_side_effect(renderable, **kwargs):
        mock_log.lines.append(MagicMock())
    mock_log.write.side_effect = write_side_effect

    renderer.add_nested_tool_call("Reading file...", depth=1, parent="Explore")

    assert mock_spacing.before_nested_tool_call.called
    assert mock_log.write.call_count == 1
    assert renderer.has_active_tools()

def test_complete_nested_tool_call(mock_log, mock_spacing):
    renderer = NestedToolRenderer(mock_log, mock_spacing)

    def write_side_effect(renderable, **kwargs):
        mock_log.lines.append(MagicMock())
    mock_log.write.side_effect = write_side_effect

    renderer.add_nested_tool_call("Reading file...", depth=1, parent="Explore", tool_id="1")

    renderer.complete_nested_tool_call("Read", 1, "Explore", True, "1")

    assert not renderer.has_active_tools()
    assert mock_log.refresh_line.called

def test_legacy_nested_tool(mock_log, mock_spacing):
    renderer = NestedToolRenderer(mock_log, mock_spacing)

    def write_side_effect(renderable, **kwargs):
        mock_log.lines.append(MagicMock())
    mock_log.write.side_effect = write_side_effect

    # This should trigger legacy path if no tool_id provided or inferred?
    # Actually add_nested_tool_call always sets self._nested_tool_line now too.
    renderer.add_nested_tool_call("Legacy...", depth=1, parent="Old")

    assert renderer._nested_tool_line is not None

    # Complete without tool_id should use legacy fallback if finding in dict fails
    # But add_nested_tool_call adds to dict too.
    # To test legacy purely, we'd need to manually set state, but that's internal.
    # The method complete_nested_tool_call tries dict first.

    renderer.complete_nested_tool_call("Legacy", 1, "Old", True)
    # It should find it via parent fallback or legacy fallback.
    assert not renderer.has_active_tools()

def test_add_nested_tool_sub_results(mock_log, mock_spacing):
    renderer = NestedToolRenderer(mock_log, mock_spacing)

    lines = ["Line 1", "Line 2", "::interrupted:: Error"]
    renderer.add_nested_tool_sub_results(lines, depth=1)

    # 3 lines -> 3 writes
    assert mock_log.write.call_count == 3

@patch("swecli.ui_textual.formatters_internal.utils.DiffParser")
def test_add_edit_diff_result(mock_diff_parser, mock_log, mock_spacing):
    renderer = NestedToolRenderer(mock_log, mock_spacing)

    # Mock DiffParser behavior
    mock_diff_parser.parse_unified_diff.return_value = [
        ("add", 10, "added line"),
        ("del", 11, "deleted line")
    ]
    mock_diff_parser.group_by_hunk.return_value = [
        (10, [("add", 10, "added line"), ("del", 11, "deleted line")])
    ]

    renderer.add_edit_diff_result("diff content", depth=1)

    # Should write lines for the hunk
    assert mock_log.write.called
