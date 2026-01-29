"""Tests for DockerToolRegistry."""

import pytest
from unittest.mock import MagicMock, ANY
from swecli.core.docker.tool_registry import DockerToolRegistry

@pytest.fixture
def mock_docker_handler():
    handler = MagicMock()
    handler.workspace_dir = "/workspace"
    # Mock sync methods
    handler.run_command_sync.return_value = {"success": True, "exit_code": 0, "output": ""}
    handler.read_file_sync.return_value = {"success": True, "content": "content"}
    handler.write_file_sync.return_value = {"success": True}
    return handler

@pytest.fixture
def mock_local_registry():
    registry = MagicMock()
    registry.execute_tool.return_value = {"success": True, "local": True}
    return registry

class TestDockerToolRegistry:

    def test_init(self, mock_docker_handler):
        """Test initialization."""
        registry = DockerToolRegistry(mock_docker_handler)
        assert registry.handler == mock_docker_handler
        assert registry._path_mapping == {}
        assert "run_command" in registry._sync_handlers

    def test_remap_paths_to_local(self, mock_docker_handler):
        """Test _remap_paths_to_local."""
        path_mapping = {
            "/workspace/paper.pdf": "/local/path/paper.pdf",
            "/workspace/src/code.py": "/local/path/src/code.py"
        }
        registry = DockerToolRegistry(mock_docker_handler, path_mapping=path_mapping)

        # Test exact match
        args = {"path": "/workspace/paper.pdf"}
        remapped = registry._remap_paths_to_local(args)
        assert remapped["path"] == "/local/path/paper.pdf"

        # Test ends with match
        args = {"path": "something/workspace/paper.pdf"} # Though typically it's exact
        # The logic is: value == docker_path or value.endswith(docker_path)

        # Test filename match
        args = {"path": "paper.pdf"}
        remapped = registry._remap_paths_to_local(args)
        assert remapped["path"] == "/local/path/paper.pdf"

        # Test no match
        args = {"path": "other.txt"}
        remapped = registry._remap_paths_to_local(args)
        assert remapped["path"] == "other.txt"

    def test_check_command_has_error(self, mock_docker_handler):
        """Test _check_command_has_error."""
        registry = DockerToolRegistry(mock_docker_handler)

        # Exit code != 0
        assert registry._check_command_has_error(1, "") is True

        # Exit code 0, no error text
        assert registry._check_command_has_error(0, "Success") is False

        # Exit code 0, but error in text
        assert registry._check_command_has_error(0, "Error: something failed") is True
        assert registry._check_command_has_error(0, "ModuleNotFoundError: x") is True
        assert registry._check_command_has_error(0, "Traceback (most recent call last)") is True

    def test_execute_tool_local_only(self, mock_docker_handler, mock_local_registry):
        """Test execution of local-only tools."""
        registry = DockerToolRegistry(
            mock_docker_handler,
            local_registry=mock_local_registry,
            path_mapping={"/workspace/doc.pdf": "/local/doc.pdf"}
        )

        # read_pdf is local only
        args = {"path": "/workspace/doc.pdf"}
        result = registry.execute_tool("read_pdf", args)

        # Should verify remapping happened
        mock_local_registry.execute_tool.assert_called_with(
            "read_pdf",
            {"path": "/local/doc.pdf"},
            mode_manager=None, approval_manager=None, undo_manager=None,
            task_monitor=None, session_manager=None, ui_callback=None, is_subagent=False
        )
        assert result["success"] is True

    def test_execute_tool_docker(self, mock_docker_handler):
        """Test execution of docker tools."""
        registry = DockerToolRegistry(mock_docker_handler)

        args = {"command": "echo hello"}
        registry.execute_tool("run_command", args)

        # Should call handler's run_command_sync (which was mocked)
        mock_docker_handler.run_command_sync.assert_called_with(
            {"command": "echo hello", "working_dir": "/workspace"}
        ) # working_dir is injected if missing

    def test_execute_tool_docker_working_dir_injected(self, mock_docker_handler):
        """Test that working_dir is injected for run_command."""
        registry = DockerToolRegistry(mock_docker_handler)

        args = {"command": "ls"}
        registry.execute_tool("run_command", args)

        mock_docker_handler.run_command_sync.assert_called_with(
            {"command": "ls", "working_dir": "/workspace"}
        )

    def test_execute_tool_docker_working_dir_preserved(self, mock_docker_handler):
        """Test that working_dir is preserved if present."""
        registry = DockerToolRegistry(mock_docker_handler)

        args = {"command": "ls", "working_dir": "/custom"}
        registry.execute_tool("run_command", args)

        mock_docker_handler.run_command_sync.assert_called_with(
            {"command": "ls", "working_dir": "/custom"}
        )

    def test_execute_tool_run_command_retry_prompt(self, mock_docker_handler):
        """Test that run_command failure injects retry prompt."""
        # Setup failure
        mock_docker_handler.run_command_sync.return_value = {
            "success": False,
            "exit_code": 1,
            "output": "Error: bad"
        }
        registry = DockerToolRegistry(mock_docker_handler)

        result = registry.execute_tool("run_command", {"command": "fail"})

        assert "_llm_suffix" in result
        assert "COMMAND FAILED" in result["_llm_suffix"]
        assert registry._last_run_command_result is not None

    def test_complete_todo_blocked(self, mock_docker_handler):
        """Test that complete_todo is blocked if last command failed."""
        registry = DockerToolRegistry(mock_docker_handler)

        # 1. Fail a command
        mock_docker_handler.run_command_sync.return_value = {
            "success": False,
            "exit_code": 1,
            "output": "Error: verification failed"
        }
        registry.execute_tool("run_command", {"command": "pytest"})

        # 2. Try complete_todo
        result = registry.execute_tool("complete_todo", {})

        assert result["success"] is False
        assert result["blocked_by"] == "command_verification"
        assert "Cannot complete todo" in result["error"]

    def test_complete_todo_cleared(self, mock_docker_handler):
        """Test that complete_todo is allowed if subsequent command succeeds."""
        registry = DockerToolRegistry(mock_docker_handler)

        # 1. Fail a command
        mock_docker_handler.run_command_sync.return_value = {
            "success": False,
            "exit_code": 1,
            "output": "Error"
        }
        registry.execute_tool("run_command", {"command": "fail"})

        # 2. Succeed a command
        mock_docker_handler.run_command_sync.return_value = {
            "success": True,
            "exit_code": 0,
            "output": "Passed"
        }
        registry.execute_tool("run_command", {"command": "pass"})

        # 3. Try complete_todo (should be passed to local registry or fail if no local registry)
        # Since we didn't provide local_registry, it will fail with "Tool not supported" or similar,
        # but NOT "blocked_by".

        result = registry.execute_tool("complete_todo", {})

        # complete_todo is not in sync_handlers and not in local_only_tools.
        # It falls through to "Try local fallback for unknown tools".
        # Since local_registry is None, it returns error "Tool not supported"
        assert result["success"] is False
        assert "not supported in Docker mode" in result["error"]
        assert "blocked_by" not in result
