"""Tests for DockerSubAgentExecutor."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
import asyncio

from swecli.core.agents.subagents.docker_execution import DockerSubAgentExecutor
from swecli.core.agents.subagents.manager import SubAgentManager, SubAgentDeps
from swecli.core.agents.subagents.specs import SubAgentSpec

class TestDockerSubAgentExecutor:
    @pytest.fixture
    def mock_manager(self):
        manager = MagicMock(spec=SubAgentManager)
        manager._working_dir = Path("/tmp/test")
        manager._extract_task_description.return_value = "Test Task"
        return manager

    @pytest.fixture
    def executor(self, mock_manager):
        return DockerSubAgentExecutor(mock_manager)

    def test_extract_input_files(self, executor, tmp_path):
        """Test extraction of input files from task description."""
        # Setup files
        pdf = tmp_path / "paper.pdf"
        pdf.touch()

        task = f"Read @{pdf.name} and summarize it."

        files = executor._extract_input_files(task, tmp_path)
        assert len(files) == 1
        assert files[0] == pdf

    def test_rewrite_task_for_docker(self, executor):
        """Test rewriting task for Docker environment."""
        task = "Read local file paper.pdf in this repo."
        input_files = [Path("/tmp/test/paper.pdf")]
        workspace_dir = "/workspace"

        # Mock manager working dir
        executor._manager._working_dir = Path("/tmp/test")

        new_task = executor._rewrite_task_for_docker(task, input_files, workspace_dir)

        assert "CRITICAL: Docker Environment" in new_task
        assert "/workspace/paper.pdf" in new_task
        assert "local" not in new_task.lower()
        assert "in /workspace" in new_task

    @patch("swecli.core.docker.deployment.DockerDeployment")
    @patch("asyncio.new_event_loop")
    @patch("asyncio.set_event_loop")
    @patch("swecli.core.docker.tool_handler.DockerToolHandler")
    def test_execute_lifecycle_success(
        self, mock_handler_cls, mock_set_loop, mock_new_loop, mock_deployment_cls, executor
    ):
        """Test successful execution lifecycle."""
        # Setup mocks
        mock_deployment = MagicMock()
        mock_deployment._container_name = "swecli-runtime-12345678"
        mock_deployment.start = AsyncMock()
        mock_deployment.stop = AsyncMock()
        mock_deployment.runtime.run = AsyncMock()
        mock_deployment_cls.return_value = mock_deployment

        mock_loop = MagicMock()
        mock_new_loop.return_value = mock_loop
        # mock_loop.run_until_complete needs to handle async calls
        mock_loop.run_until_complete.side_effect = lambda x: None

        spec = SubAgentSpec(
            name="TestAgent",
            description="Test",
            system_prompt="Prompt",
            docker_config=MagicMock(image="test-image")
        )

        deps = MagicMock(spec=SubAgentDeps)

        executor._manager.execute_subagent.return_value = {"success": True, "content": "Done"}

        # Execute
        result = executor.execute_lifecycle(
            name="TestAgent",
            task="Do it",
            deps=deps,
            spec=spec
        )

        assert result["success"] is True
        assert result["content"] == "Done"

        # Verify lifecycle
        mock_deployment_cls.assert_called_once()
        # We can't easily assert run_until_complete calls because we mocked the loop
        # But we can assert manager.execute_subagent was called
        executor._manager.execute_subagent.assert_called_once()

        # Verify stop was called (via loop or directly if we could track it)
        # Since loop is mocked, we assume the logic called deployment.stop() inside loop.run_until_complete
        # Ideally we'd verify deployment.stop() was passed to run_until_complete

    def test_create_docker_path_sanitizer(self, executor):
        """Test path sanitizer creation and functionality."""
        sanitizer = executor._create_docker_path_sanitizer(
            workspace_dir="/workspace",
            local_dir="/local/path",
            image_name="ghcr.io/astral-sh/uv:python3.11",
            container_id="12345678"
        )

        # Test local path conversion
        assert sanitizer("/local/path/file.py") == "[uv:12345678]:/workspace/file.py"

        # Test workspace path preservation
        assert sanitizer("/workspace/file.py") == "[uv:12345678]:/workspace/file.py"

        # Test relative path conversion
        assert sanitizer("file.py") == "[uv:12345678]:/workspace/file.py"
