import pytest
from unittest.mock import AsyncMock, Mock, patch
from swecli.core.docker.tools.search import SearchTool

@pytest.fixture
def mock_runtime():
    return AsyncMock()

@pytest.mark.asyncio
async def test_search_text(mock_runtime):
    tool = SearchTool(mock_runtime, "/workspace")

    mock_obs = Mock()
    mock_obs.exit_code = 0
    mock_obs.output = "match1\nmatch2"
    mock_runtime.run.return_value = mock_obs

    result = await tool.execute({"query": "search_term", "path": "."})

    assert result["success"] is True
    assert result["output"] == "match1\nmatch2"

    args, _ = mock_runtime.run.call_args
    assert "grep" in args[0]
    assert "search_term" in args[0]

@pytest.mark.asyncio
async def test_search_missing_query(mock_runtime):
    tool = SearchTool(mock_runtime, "/workspace")
    result = await tool.execute({})

    assert result["success"] is False
    assert "query is required" in result["error"]
