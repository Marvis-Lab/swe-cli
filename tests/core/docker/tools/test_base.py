import pytest
from unittest.mock import AsyncMock, Mock, patch
from swecli.core.docker.tools.base import DockerToolBase

@pytest.fixture
def mock_runtime():
    return AsyncMock()

def test_docker_tool_base_init(mock_runtime):
    tool = DockerToolBase(mock_runtime, "/workspace")
    assert tool.runtime == mock_runtime
    assert tool.workspace_dir == "/workspace"

def test_translate_path(mock_runtime):
    tool = DockerToolBase(mock_runtime, "/workspace")

    # Relative path
    assert tool._translate_path("file.txt") == "/workspace/file.txt"
    assert tool._translate_path("./file.txt") == "/workspace/file.txt"

    # Absolute container path
    assert tool._translate_path("/workspace/file.txt") == "/workspace/file.txt"
    assert tool._translate_path("/testbed/file.txt") == "/testbed/file.txt"

    # Absolute host path
    assert tool._translate_path("/Users/user/project/file.txt") == "/workspace/file.txt"

    # Empty path
    assert tool._translate_path("") == "/workspace"
