"""Tests for ToolCommands handler."""

from unittest.mock import MagicMock, patch
import pytest
from rich.console import Console

from swecli.repl.commands.tool_commands import ToolCommands
from swecli.models.operation import Operation, OperationType


@pytest.fixture
def mock_dependencies():
    """Create mock dependencies for ToolCommands."""
    return {
        "console": MagicMock(spec=Console),
        "config": MagicMock(),
        "config_manager": MagicMock(),
        "mode_manager": MagicMock(),
        "approval_manager": MagicMock(),
        "undo_manager": MagicMock(),
        "session_manager": MagicMock(),
        "mcp_manager": MagicMock(),
        "runtime_suite": MagicMock(),
        "bash_tool": MagicMock(),
        "error_handler": MagicMock(),
        "agent": MagicMock(),
    }


@pytest.fixture
def tool_commands(mock_dependencies):
    """Create ToolCommands instance."""
    return ToolCommands(**mock_dependencies)


def test_init_command(tool_commands, mock_dependencies):
    """Test /init command."""
    with patch("swecli.commands.init_command.InitCommandHandler") as MockHandler:
        mock_handler_instance = MockHandler.return_value
        mock_handler_instance.parse_args.return_value = "args"
        mock_handler_instance.execute.return_value = {
            "success": True,
            "message": "Init successful",
            "content": "AGENTS.md"
        }

        tool_commands.init_codebase("/init")

        MockHandler.assert_called_once()
        mock_handler_instance.execute.assert_called_once()
        mock_dependencies["console"].print.assert_called()


def test_run_command_success(tool_commands, mock_dependencies):
    """Test /run command success path."""
    mock_dependencies["config"].enable_bash = True
    mock_dependencies["mode_manager"].needs_approval.return_value = False

    mock_bash_result = MagicMock()
    mock_bash_result.success = True
    mock_bash_result.stdout = "output"
    mock_bash_result.stderr = ""
    mock_bash_result.exit_code = 0
    mock_dependencies["bash_tool"].execute.return_value = mock_bash_result

    tool_commands.run_command("ls -la")

    mock_dependencies["bash_tool"].execute.assert_called_once()
    mock_dependencies["undo_manager"].record_operation.assert_called_once()
    mock_dependencies["console"].print.assert_called()


def test_run_command_disabled(tool_commands, mock_dependencies):
    """Test /run command when bash is disabled."""
    mock_dependencies["config"].enable_bash = False

    tool_commands.run_command("ls")

    mock_dependencies["bash_tool"].execute.assert_not_called()
    mock_dependencies["console"].print.assert_called()


def test_resolve_issue_success(tool_commands, mock_dependencies):
    """Test /resolve-github-issue command."""
    with patch("swecli.commands.issue_resolver.IssueResolverCommand") as MockHandler:
        mock_handler_instance = MockHandler.return_value
        mock_handler_instance.parse_args.return_value = "args"

        mock_metadata = MagicMock()
        mock_metadata.pr_url = "http://pr"
        mock_metadata.repo_path = "/path"
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "Fixed"
        mock_result.metadata = mock_metadata
        mock_handler_instance.execute.return_value = mock_result

        # Mock subagent manager presence
        mock_dependencies["runtime_suite"].agents.subagent_manager = MagicMock()
        mock_dependencies["config_manager"].working_dir = "/work/dir"

        tool_commands.resolve_issue("/resolve-github-issue http://github.com/issue/1")

        MockHandler.assert_called_once()
        # Verify working_dir is passed correctly
        call_kwargs = MockHandler.call_args.kwargs
        assert call_kwargs["working_dir"] == "/work/dir"

        mock_handler_instance.execute.assert_called_once()
        mock_dependencies["console"].print.assert_called()


def test_paper2code_success(tool_commands, mock_dependencies):
    """Test /paper2code command."""
    with patch("swecli.commands.paper2code_command.Paper2CodeCommand") as MockHandler:
        mock_handler_instance = MockHandler.return_value
        mock_args = MagicMock()
        mock_args.pdf_path = "paper.pdf"
        mock_handler_instance.parse_args.return_value = mock_args

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "Generated"
        mock_result.output_path = "/path/code"
        mock_handler_instance.execute.return_value = mock_result

        # Mock subagent manager presence
        mock_dependencies["runtime_suite"].agents.subagent_manager = MagicMock()
        mock_dependencies["config_manager"].working_dir = "/work/dir"

        tool_commands.paper2code("/paper2code paper.pdf")

        MockHandler.assert_called_once()
        # Verify working_dir is passed correctly
        call_kwargs = MockHandler.call_args.kwargs
        assert call_kwargs["working_dir"] == "/work/dir"

        mock_handler_instance.execute.assert_called_once()
        mock_dependencies["console"].print.assert_called()
