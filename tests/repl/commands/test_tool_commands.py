"""Tests for ToolCommands handler."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from swecli.repl.commands.tool_commands import ToolCommands


@pytest.fixture
def mock_dependencies():
    """Create mock dependencies for ToolCommands."""
    mock_runtime_suite = MagicMock()
    mock_subagent_manager = MagicMock()
    mock_agents = MagicMock()
    mock_agents.subagent_manager = mock_subagent_manager
    mock_runtime_suite.agents = mock_agents

    return {
        "console": MagicMock(spec=Console),
        "config": MagicMock(),
        "config_manager": MagicMock(),
        "mode_manager": MagicMock(),
        "approval_manager": MagicMock(),
        "undo_manager": MagicMock(),
        "session_manager": MagicMock(),
        "mcp_manager": MagicMock(),
        "runtime_suite": mock_runtime_suite,
        "bash_tool": MagicMock(),
        "error_handler": MagicMock(),
        "agent": MagicMock(),
    }


@pytest.fixture
def tool_commands(mock_dependencies):
    """Create ToolCommands instance."""
    return ToolCommands(**mock_dependencies)


def test_init_command(tool_commands, mock_dependencies, tmp_path):
    """Test /init command dispatches to Init subagent."""
    mock_subagent_manager = mock_dependencies["runtime_suite"].agents.subagent_manager
    mock_subagent_manager.execute_subagent.return_value = {
        "success": True,
        "content": "Generated OPENDEV.md",
    }

    # Create a fake OPENDEV.md to simulate success
    opendev_path = tmp_path / "OPENDEV.md"
    opendev_path.write_text("# Test")

    with patch("swecli.repl.commands.tool_commands.Path") as MockPath:
        MockPath.cwd.return_value = tmp_path
        # Make Path(parts[1]) work for path parsing
        MockPath.return_value.expanduser.return_value.absolute.return_value = tmp_path
        MockPath.return_value.exists.return_value = True
        MockPath.return_value.is_dir.return_value = True

        tool_commands.init_codebase(f"/init {tmp_path}")

    mock_subagent_manager.execute_subagent.assert_called_once()
    call_kwargs = mock_subagent_manager.execute_subagent.call_args[1]
    assert call_kwargs["name"] == "Init"
    assert "task" in call_kwargs


def test_init_command_invalid_path(tool_commands, mock_dependencies):
    """Test /init command with invalid path."""
    tool_commands.init_codebase("/init /nonexistent/path")
    mock_dependencies["console"].print.assert_called()


