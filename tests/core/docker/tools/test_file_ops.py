import pytest
from unittest.mock import AsyncMock, Mock, patch
from swecli.core.docker.tools.file_ops import FileOperationsTool

@pytest.fixture
def mock_runtime():
    return AsyncMock()

@pytest.mark.asyncio
async def test_read_file(mock_runtime):
    tool = FileOperationsTool(mock_runtime, "/workspace")

    mock_runtime.read_file.return_value = "file content"

    result = await tool.read_file({"path": "file.txt"})

    assert result["success"] is True
    assert result["content"] == "file content"
    mock_runtime.read_file.assert_called_with("/workspace/file.txt")

@pytest.mark.asyncio
async def test_write_file(mock_runtime):
    tool = FileOperationsTool(mock_runtime, "/workspace")

    result = await tool.write_file({"path": "file.txt", "content": "new content"})

    assert result["success"] is True
    mock_runtime.write_file.assert_called_with("/workspace/file.txt", "new content")

@pytest.mark.asyncio
async def test_edit_file(mock_runtime):
    tool = FileOperationsTool(mock_runtime, "/workspace")

    mock_runtime.read_file.return_value = "line1\nline2\nline3"

    result = await tool.edit_file({
        "path": "file.txt",
        "old_text": "line2",
        "new_text": "new line2"
    })

    assert result["success"] is True
    mock_runtime.write_file.assert_called_with("/workspace/file.txt", "line1\nnew line2\nline3")

def test_find_content():
    tool = FileOperationsTool(None, "/workspace")

    original = "line1\n  line2  \nline3"

    # Exact match
    found, actual = tool._find_content(original, "  line2  ")
    assert found
    assert actual == "  line2  "

    # Normalized match
    found, actual = tool._find_content(original, "line2")
    assert found
    assert actual.strip() == "line2"
