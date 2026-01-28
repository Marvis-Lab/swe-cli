"""Tests for DockerToolRegistry."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock


class TestSanitizeLocalPaths:
    """Test the _sanitize_local_paths method in DockerToolRegistry."""

    def _create_registry(self):
        """Create a minimal DockerToolRegistry for testing."""
        from swecli.core.docker.tool_registry import DockerToolRegistry
        from swecli.core.docker.tool_handler import DockerToolHandler

        # Create a mock docker handler
        mock_runtime = MagicMock()
        mock_runtime.host = "localhost"
        mock_runtime.port = 8000
        mock_runtime.auth_token = "test"
        mock_runtime.timeout = 30.0

        handler = DockerToolHandler(mock_runtime, workspace_dir="/workspace")
        return DockerToolRegistry(handler)

    def test_sanitize_users_path(self):
        """Test that /Users/... paths are sanitized to just filename."""
        registry = self._create_registry()
        args = {"path": "/Users/nghibui/codes/test_opencli/pyproject.toml"}
        result = registry._sanitize_local_paths(args)
        assert result["path"] == "pyproject.toml"

    def test_sanitize_home_path(self):
        """Test that /home/... paths are sanitized to just filename."""
        registry = self._create_registry()
        args = {"file_path": "/home/user/project/src/model.py"}
        result = registry._sanitize_local_paths(args)
        assert result["file_path"] == "model.py"

    def test_sanitize_var_path(self):
        """Test that /var/... paths are sanitized to just filename."""
        registry = self._create_registry()
        args = {"path": "/var/tmp/data/config.yaml"}
        result = registry._sanitize_local_paths(args)
        assert result["path"] == "config.yaml"

    def test_sanitize_tmp_path(self):
        """Test that /tmp/... paths are sanitized to just filename."""
        registry = self._create_registry()
        args = {"path": "/tmp/working/file.txt"}
        result = registry._sanitize_local_paths(args)
        assert result["path"] == "file.txt"

    def test_preserve_relative_path(self):
        """Test that relative paths are preserved."""
        registry = self._create_registry()
        args = {"path": "src/model.py"}
        result = registry._sanitize_local_paths(args)
        assert result["path"] == "src/model.py"

    def test_preserve_workspace_path(self):
        """Test that /workspace/... paths are preserved."""
        registry = self._create_registry()
        args = {"path": "/workspace/src/model.py"}
        result = registry._sanitize_local_paths(args)
        # This starts with /workspace, not /Users, so should be preserved
        assert result["path"] == "/workspace/src/model.py"

    def test_preserve_testbed_path(self):
        """Test that /testbed/... paths are preserved."""
        registry = self._create_registry()
        args = {"path": "/testbed/src/model.py"}
        result = registry._sanitize_local_paths(args)
        assert result["path"] == "/testbed/src/model.py"

    def test_sanitize_multiple_args(self):
        """Test sanitizing multiple path arguments."""
        registry = self._create_registry()
        args = {
            "file_path": "/Users/nghibui/codes/test/main.py",
            "content": "print('hello')",  # Non-path, should be preserved
            "output_path": "/home/user/output.txt",
        }
        result = registry._sanitize_local_paths(args)
        assert result["file_path"] == "main.py"
        assert result["content"] == "print('hello')"
        assert result["output_path"] == "output.txt"

    def test_sanitize_pdf_path(self):
        """Test sanitizing PDF file paths."""
        registry = self._create_registry()
        args = {"path": "/Users/nghibui/codes/test_opencli/2303.11366v4.pdf"}
        result = registry._sanitize_local_paths(args)
        assert result["path"] == "2303.11366v4.pdf"


class TestDockerToolRegistryExecution:
    """Test execution and routing logic in DockerToolRegistry."""

    def _create_registry(self, local_registry=None, path_mapping=None):
        """Create a DockerToolRegistry with mocks."""
        from swecli.core.docker.tool_registry import DockerToolRegistry
        from swecli.core.docker.tool_handler import DockerToolHandler

        mock_handler = MagicMock(spec=DockerToolHandler)
        mock_handler.workspace_dir = "/workspace"
        # Setup sync handlers
        mock_handler.run_command_sync = MagicMock(return_value={"success": True, "output": ""})
        mock_handler.read_file_sync = MagicMock(return_value={"success": True, "output": ""})

        return DockerToolRegistry(mock_handler, local_registry, path_mapping), mock_handler

    def test_execute_tool_docker_routing(self):
        """Test that supported tools are routed to Docker handler."""
        registry, mock_handler = self._create_registry()

        registry.execute_tool("run_command", {"command": "ls"})

        mock_handler.run_command_sync.assert_called_once()
        args = mock_handler.run_command_sync.call_args[0][0]
        assert args["command"] == "ls"
        # verify default working_dir injection
        assert args["working_dir"] == "/workspace"

    def test_execute_tool_local_routing(self):
        """Test that local-only tools are routed to local registry."""
        mock_local = MagicMock()
        mock_local.execute_tool.return_value = {"success": True, "local": True}

        registry, _ = self._create_registry(local_registry=mock_local)

        result = registry.execute_tool("read_pdf", {"path": "paper.pdf"})

        assert result["local"] is True
        mock_local.execute_tool.assert_called_once()
        assert mock_local.execute_tool.call_args[0][0] == "read_pdf"

    def test_remap_paths_to_local(self):
        """Test path remapping for local tools."""
        mapping = {"/workspace/paper.pdf": "/local/path/paper.pdf"}
        registry, _ = self._create_registry(path_mapping=mapping)

        # Access private method directly to test logic
        args = {"path": "/workspace/paper.pdf"}
        remapped = registry._remap_paths_to_local(args)
        assert remapped["path"] == "/local/path/paper.pdf"

        # Test filename match
        args = {"path": "paper.pdf"}
        remapped = registry._remap_paths_to_local(args)
        assert remapped["path"] == "/local/path/paper.pdf"

    def test_check_command_has_error(self):
        """Test error detection in command output."""
        registry, _ = self._create_registry()

        assert registry._check_command_has_error(1, "") is True
        assert registry._check_command_has_error(0, "Error: something failed") is True
        assert registry._check_command_has_error(0, "Traceback (most recent call last)") is True
        assert registry._check_command_has_error(0, "Everything is fine") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
