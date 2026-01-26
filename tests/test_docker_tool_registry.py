"""Unit tests for DockerToolRegistry."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from swecli.core.docker.tool_handler import DockerToolHandler
from swecli.core.docker.tool_registry import DockerToolRegistry


class TestDockerToolRegistry:
    """Test DockerToolRegistry routing and logic."""

    @pytest.fixture
    def mock_handler(self):
        """Create a mock DockerToolHandler."""
        handler = MagicMock(spec=DockerToolHandler)
        handler.workspace_dir = "/workspace"

        # Setup sync methods as mocks since registry calls them
        handler.run_command_sync = MagicMock(return_value={"success": True, "output": "ok", "exit_code": 0})
        handler.read_file_sync = MagicMock(return_value={"success": True, "content": "content"})
        handler.write_file_sync = MagicMock(return_value={"success": True})
        handler.edit_file_sync = MagicMock(return_value={"success": True})
        handler.list_files_sync = MagicMock(return_value={"success": True, "output": "files"})
        handler.search_sync = MagicMock(return_value={"success": True, "output": "matches"})

        return handler

    @pytest.fixture
    def mock_local_registry(self):
        """Create a mock local ToolRegistry."""
        registry = MagicMock()
        registry.execute_tool = MagicMock(return_value={"success": True, "local": True})
        return registry

    @pytest.fixture
    def registry(self, mock_handler, mock_local_registry):
        """Create a DockerToolRegistry with mocks."""
        return DockerToolRegistry(
            docker_handler=mock_handler,
            local_registry=mock_local_registry,
            path_mapping={"/workspace/paper.pdf": "/local/paper.pdf"}
        )

    def test_routes_supported_tool_to_docker(self, registry, mock_handler):
        """Test that supported tools are routed to the Docker handler."""
        result = registry.execute_tool("read_file", {"path": "src/main.py"})

        assert result["success"] is True
        # Should call the sync wrapper
        mock_handler.read_file_sync.assert_called_once_with({"path": "src/main.py"})

    def test_routes_local_only_tool_to_local_registry(self, registry, mock_local_registry):
        """Test that local-only tools are routed to the local registry."""
        result = registry.execute_tool("read_pdf", {"file_path": "/workspace/paper.pdf"})

        assert result["local"] is True
        # Arguments should be remapped
        mock_local_registry.execute_tool.assert_called_once()
        args = mock_local_registry.execute_tool.call_args[0][1]
        assert args["file_path"] == "/local/paper.pdf"

    def test_routes_unknown_tool_to_local_registry(self, registry, mock_local_registry):
        """Test that unknown tools are routed to the local registry."""
        result = registry.execute_tool("some_custom_tool", {"arg": "value"})

        assert result["local"] is True
        mock_local_registry.execute_tool.assert_called_once()
        assert mock_local_registry.execute_tool.call_args[0][0] == "some_custom_tool"

    def test_remap_paths_to_local(self, registry):
        """Test path remapping logic."""
        # Exact match
        args = {"path": "/workspace/paper.pdf"}
        remapped = registry._remap_paths_to_local(args)
        assert remapped["path"] == "/local/paper.pdf"

        # Filename match
        args = {"path": "paper.pdf"}
        remapped = registry._remap_paths_to_local(args)
        assert remapped["path"] == "/local/paper.pdf"

        # No match
        args = {"path": "other.pdf"}
        remapped = registry._remap_paths_to_local(args)
        assert remapped["path"] == "other.pdf"

    def test_sanitize_local_paths(self, registry):
        """Test sanitization of absolute local paths."""
        args = {"path": "/Users/user/project/file.py"}
        sanitized = registry._sanitize_local_paths(args)
        assert sanitized["path"] == "file.py"

        args = {"path": "/home/user/file.py"}
        sanitized = registry._sanitize_local_paths(args)
        assert sanitized["path"] == "file.py"

        # Relative paths untouched
        args = {"path": "src/file.py"}
        sanitized = registry._sanitize_local_paths(args)
        assert sanitized["path"] == "src/file.py"

    def test_injects_default_working_dir_for_run_command(self, registry, mock_handler):
        """Test that working_dir is injected for run_command if missing."""
        registry.execute_tool("run_command", {"command": "ls"})

        mock_handler.run_command_sync.assert_called_once()
        args = mock_handler.run_command_sync.call_args[0][0]
        assert args["working_dir"] == "/workspace"
        assert args["command"] == "ls"

    def test_blocks_complete_todo_after_failed_command(self, registry, mock_handler):
        """Test that complete_todo is blocked if the last run_command failed."""
        # Simulate failed command
        mock_handler.run_command_sync.return_value = {
            "success": False,
            "exit_code": 1,
            "output": "Error: failed"
        }

        # Run command
        registry.execute_tool("run_command", {"command": "fail"})

        # Try to complete todo
        result = registry.execute_tool("complete_todo", {})

        assert result["success"] is False
        assert result["blocked_by"] == "command_verification"
        assert "Cannot complete todo" in result["error"]

    def test_allows_complete_todo_after_successful_command(self, registry, mock_handler):
        """Test that complete_todo is allowed if the last run_command succeeded."""
        # 1. Fail first
        mock_handler.run_command_sync.return_value = {
            "success": False,
            "exit_code": 1,
            "output": "Error: failed"
        }
        registry.execute_tool("run_command", {"command": "fail"})

        # 2. Succeed next
        mock_handler.run_command_sync.return_value = {
            "success": True,
            "exit_code": 0,
            "output": "ok"
        }
        registry.execute_tool("run_command", {"command": "succeed"})

        # 3. Complete todo (should be routed to local registry)
        result = registry.execute_tool("complete_todo", {})

        assert result["local"] is True  # Mock local registry returns this

    def test_injects_retry_prompt_on_command_failure(self, registry, mock_handler):
        """Test that retry prompt is injected into _llm_suffix on failure."""
        mock_handler.run_command_sync.return_value = {
            "success": False,
            "exit_code": 1,
            "output": "Error: failed"
        }

        result = registry.execute_tool("run_command", {"command": "fail"})

        assert "_llm_suffix" in result
        assert "COMMAND FAILED" in result["_llm_suffix"]

    @pytest.mark.asyncio
    async def test_execute_tool_async(self, registry, mock_handler):
        """Test execute_tool_async delegates to async handlers."""
        # Setup async mock for handler
        mock_handler.read_file = AsyncMock(return_value={"success": True, "content": "async content"})

        result = await registry.execute_tool_async("read_file", {"path": "test.py"})

        assert result["success"] is True
        assert result["content"] == "async content"
        mock_handler.read_file.assert_called_once()
