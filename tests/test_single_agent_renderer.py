import pytest
from unittest.mock import MagicMock, ANY
from rich.text import Text
from textual.strip import Strip

from swecli.ui_textual.widgets.conversation.renderers.single_agent_renderer import SingleAgentRenderer
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

def test_on_single_agent_start(mock_log, mock_spacing):
    renderer = SingleAgentRenderer(mock_log, mock_spacing)

    def write_side_effect(renderable, **kwargs):
        mock_log.lines.append(MagicMock())
    mock_log.write.side_effect = write_side_effect

    renderer.on_single_agent_start("Explore", "Exploring", "1")

    assert mock_spacing.before_single_agent.called
    assert mock_log.write.call_count == 3 # Header, status, tool
    assert renderer.agent is not None
    assert renderer.agent.tool_call_id == "1"
    assert renderer.agent.status == "running"

def test_on_tool_call(mock_log, mock_spacing):
    renderer = SingleAgentRenderer(mock_log, mock_spacing)

    renderer.on_single_agent_start("Explore", "Exploring", "1")
    mock_log.lines = [MagicMock(), MagicMock(), MagicMock()] # Lines created by start

    renderer.on_tool_call("ls -la")

    assert renderer.agent.tool_count == 1
    assert renderer.agent.current_tool == "ls -la"
    # updates header (spinner), status (count), tool (name)
    assert mock_log.refresh_line.call_count == 3

def test_on_single_agent_complete(mock_log, mock_spacing):
    renderer = SingleAgentRenderer(mock_log, mock_spacing)

    renderer.on_single_agent_start("Explore", "Exploring", "1")
    mock_log.lines = [MagicMock(), MagicMock(), MagicMock()]

    renderer.on_single_agent_complete("1", success=True)

    assert renderer.agent is None
    assert mock_spacing.after_single_agent.called
    assert mock_log.refresh_line.call_count == 3

def test_has_active_agent(mock_log, mock_spacing):
    renderer = SingleAgentRenderer(mock_log, mock_spacing)

    def write_side_effect(renderable, **kwargs):
        mock_log.lines.append(MagicMock())
    mock_log.write.side_effect = write_side_effect

    assert not renderer.has_active_agent()

    renderer.on_single_agent_start("Explore", "Exploring", "1")
    assert renderer.has_active_agent()

    renderer.on_single_agent_complete("1", success=True)
    assert not renderer.has_active_agent()

def test_adjust_indices(mock_log, mock_spacing):
    renderer = SingleAgentRenderer(mock_log, mock_spacing)

    def write_side_effect(renderable, **kwargs):
        mock_log.lines.append(MagicMock())
    mock_log.write.side_effect = write_side_effect

    renderer.on_single_agent_start("Explore", "Exploring", "1")
    # Initial lines: 0, 1, 2

    renderer.adjust_indices(2, 0)

    assert renderer.agent.header_line == 2
    assert renderer.agent.status_line == 3
    assert renderer.agent.tool_line == 4
