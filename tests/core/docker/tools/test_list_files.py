import pytest
from unittest.mock import AsyncMock, Mock, patch
from swecli.core.docker.tools.list_files import ListFilesTool

@pytest.fixture
def mock_runtime():
    return AsyncMock()

@pytest.mark.asyncio
async def test_list_files(mock_runtime):
    tool = ListFilesTool(mock_runtime, "/workspace")

    mock_obs = Mock()
    mock_obs.exit_code = 0
    mock_obs.output = "file1.txt\nfile2.txt"
    mock_runtime.run.return_value = mock_obs

    result = await tool.execute({"path": "."})

    assert result["success"] is True
    assert result["output"] == "file1.txt\nfile2.txt"
    mock_runtime.run.assert_called()

@pytest.mark.asyncio
async def test_list_files_recursive(mock_runtime):
    tool = ListFilesTool(mock_runtime, "/workspace")

    mock_obs = Mock()
    mock_obs.exit_code = 0
    mock_runtime.run.return_value = mock_obs

    await tool.execute({"path": ".", "recursive": True})

    args, _ = mock_runtime.run.call_args
    assert "find" in args[0]

@pytest.mark.asyncio
async def test_list_files_failure(mock_runtime):
    tool = ListFilesTool(mock_runtime, "/workspace")

    mock_obs = Mock()
    mock_obs.exit_code = 1
    mock_obs.output = "Directory not found"
    mock_obs.failure_reason = None
    mock_runtime.run.return_value = mock_obs

    result = await tool.execute({"path": "nonexistent"})

    assert result["success"] is False
    assert "Directory not found" in result["error"]
