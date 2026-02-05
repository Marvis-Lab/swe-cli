import pytest
from unittest.mock import MagicMock, ANY
from rich.text import Text
from textual.strip import Strip

from swecli.ui_textual.widgets.conversation.renderers.parallel_agent_renderer import ParallelAgentRenderer
from swecli.ui_textual.widgets.conversation.renderers.models import ParallelAgentGroup, AgentInfo
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

def test_on_parallel_agents_start(mock_log, mock_spacing):
    renderer = ParallelAgentRenderer(mock_log, mock_spacing)

    # Mock log lines to simulate write operations adding lines
    def write_side_effect(renderable, **kwargs):
        mock_log.lines.append(MagicMock())
    mock_log.write.side_effect = write_side_effect

    agent_infos = [
        {"tool_call_id": "1", "agent_type": "Explore", "description": "Exploring"},
        {"tool_call_id": "2", "agent_type": "Code", "description": "Coding"}
    ]

    renderer.on_parallel_agents_start(agent_infos)

    assert mock_spacing.before_parallel_agents.called
    # Header + 2 * (Agent row + Status row) = 1 + 4 = 5 writes
    assert mock_log.write.call_count == 5
    assert renderer.group is not None
    assert len(renderer.group.agents) == 2
    assert "1" in renderer.group.agents
    assert "2" in renderer.group.agents

def test_update_agent_tool(mock_log, mock_spacing):
    renderer = ParallelAgentRenderer(mock_log, mock_spacing)

    # Setup group manually
    agent = AgentInfo(agent_type="Test", description="desc", tool_call_id="1", line_number=0, status_line=1)
    renderer.group = ParallelAgentGroup(agents={"1": agent})

    # Mock log lines access
    mock_log.lines = [MagicMock(), MagicMock()]

    renderer.update_agent_tool("1", "ls -la")

    assert agent.tool_count == 1
    assert agent.current_tool == "ls -la"
    assert mock_log.refresh_line.call_count == 2 # Once for row, once for status

def test_on_parallel_agent_complete(mock_log, mock_spacing):
    renderer = ParallelAgentRenderer(mock_log, mock_spacing)

    agent = AgentInfo(agent_type="Test", description="desc", tool_call_id="1", line_number=0, status_line=1)
    renderer.group = ParallelAgentGroup(agents={"1": agent})
    mock_log.lines = [MagicMock(), MagicMock(), MagicMock()] # Extra for header
    renderer.group.header_line = 2

    renderer.on_parallel_agent_complete("1", success=True)

    assert agent.status == "completed"
    assert mock_log.refresh_line.call_count == 3 # Row, status, header

def test_on_parallel_agents_done(mock_log, mock_spacing):
    renderer = ParallelAgentRenderer(mock_log, mock_spacing)

    agent1 = AgentInfo(agent_type="Test", description="desc", tool_call_id="1", line_number=0, status_line=1, status="completed")
    agent2 = AgentInfo(agent_type="Test", description="desc", tool_call_id="2", line_number=2, status_line=3, status="running")
    renderer.group = ParallelAgentGroup(agents={"1": agent1, "2": agent2})
    mock_log.lines = [MagicMock()] * 5
    renderer.group.header_line = 4

    renderer.on_parallel_agents_done()

    assert renderer.group is None
    assert agent2.status == "completed"
    assert mock_spacing.after_parallel_agents.called

def test_toggle_expansion(mock_log, mock_spacing):
    renderer = ParallelAgentRenderer(mock_log, mock_spacing)
    assert not renderer.expanded

    expanded = renderer.toggle_expansion()
    assert expanded
    assert renderer.expanded

    renderer.group = ParallelAgentGroup()
    renderer.toggle_expansion()
    assert not renderer.expanded
    assert not renderer.group.expanded

def test_adjust_indices(mock_log, mock_spacing):
    renderer = ParallelAgentRenderer(mock_log, mock_spacing)

    agent = AgentInfo(agent_type="Test", description="desc", tool_call_id="1", line_number=10, status_line=11)
    renderer.group = ParallelAgentGroup(agents={"1": agent}, header_line=9)

    # Adjust lines after 5 by +2
    renderer.adjust_indices(2, 5)

    assert renderer.group.header_line == 11
    assert agent.line_number == 12
    assert agent.status_line == 13

    # Adjust lines after 15 (should not affect)
    renderer.adjust_indices(2, 15)

    assert renderer.group.header_line == 11
