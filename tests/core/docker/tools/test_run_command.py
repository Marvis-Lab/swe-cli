import pytest
from unittest.mock import AsyncMock, Mock, patch
from swecli.core.docker.tools.run_command import RunCommandTool
from swecli.core.docker.models import BashAction

@pytest.fixture
def mock_runtime():
    runtime = AsyncMock()
    runtime.run_in_session = AsyncMock()
    return runtime

@pytest.mark.asyncio
async def test_run_command_success(mock_runtime):
    tool = RunCommandTool(mock_runtime, "/workspace")

    mock_obs = Mock()
    mock_obs.exit_code = 0
    mock_obs.output = "Success"
    mock_runtime.run_in_session.return_value = mock_obs

    result = await tool.execute({"command": "echo hello"})

    assert result["success"] is True
    assert result["output"] == "Success"
    assert result["exit_code"] == 0

    # Check that BashAction was called correctly
    args, kwargs = mock_runtime.run_in_session.call_args
    action = args[0]
    assert isinstance(action, BashAction)
    assert action.command == "echo hello"

@pytest.mark.asyncio
async def test_run_command_with_working_dir(mock_runtime):
    tool = RunCommandTool(mock_runtime, "/workspace")

    mock_obs = Mock()
    mock_obs.exit_code = 0
    mock_obs.output = "Success"
    mock_runtime.run_in_session.return_value = mock_obs

    result = await tool.execute({"command": "ls", "working_dir": "subdir"})

    args, kwargs = mock_runtime.run_in_session.call_args
    action = args[0]
    assert "cd /workspace/subdir" in action.command

@pytest.mark.asyncio
async def test_run_command_with_shell_init(mock_runtime):
    tool = RunCommandTool(mock_runtime, "/workspace", shell_init="source setup.sh")

    mock_obs = Mock()
    mock_obs.exit_code = 0
    mock_obs.output = "Success"
    mock_runtime.run_in_session.return_value = mock_obs

    result = await tool.execute({"command": "python script.py"})

    args, kwargs = mock_runtime.run_in_session.call_args
    action = args[0]
    assert action.command == "source setup.sh && python script.py"

@pytest.mark.asyncio
async def test_run_command_missing_command(mock_runtime):
    tool = RunCommandTool(mock_runtime, "/workspace")
    result = await tool.execute({})

    assert result["success"] is False
    assert result["error"] == "command is required"
