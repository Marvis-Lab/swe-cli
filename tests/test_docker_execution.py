"""Unit tests for DockerSubAgentExecutor."""

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
        manager._extract_task_description.return_value = "Test task"
        manager._agents = {}
        return manager

    @pytest.fixture
    def executor(self, mock_manager):
        return DockerSubAgentExecutor(mock_manager)

    @patch("shutil.which")
    def test_is_docker_available(self, mock_which, executor):
        mock_which.return_value = "/usr/bin/docker"
        assert executor.is_docker_available() is True

        mock_which.return_value = None
        assert executor.is_docker_available() is False

    def test_extract_input_files(self, executor):
        task = "Check @file1.pdf and 'file2.docx'"
        local_dir = Path("/tmp")

        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "is_file", return_value=True):
            files = executor.extract_input_files(task, local_dir)
            names = [f.name for f in files]
            assert "file1.pdf" in names
            assert "file2.docx" in names

    def test_rewrite_task_for_docker(self, executor):
        task = "Check local file @paper.pdf in this repo"
        files = [Path("/tmp/paper.pdf")]
        workspace = "/workspace"

        executor.manager._working_dir = Path("/tmp")

        new_task = executor.rewrite_task_for_docker(task, files, workspace)

        assert "CRITICAL: Docker Environment" in new_task
        assert "/workspace/paper.pdf" in new_task
        assert "local" not in new_task.lower()
        assert "in /workspace" in new_task # "in this repo" -> "in /workspace"

    @patch("swecli.core.agents.subagents.docker_execution.DockerSubAgentExecutor.create_nested_callback")
    @patch("swecli.core.docker.deployment.DockerDeployment")
    @patch("swecli.core.docker.tool_handler.DockerToolHandler")
    @patch("asyncio.new_event_loop")
    @patch("asyncio.set_event_loop")
    def test_execute_success(
        self, mock_set_loop, mock_new_loop, mock_handler_cls, mock_deployment_cls, mock_create_callback, executor
    ):
        # Setup mocks
        mock_loop = MagicMock()
        # Mock run_until_complete to execute the coroutine if passed, or just return
        def run_until_complete(coro):
            if asyncio.iscoroutine(coro):
                # We can't await it here, but we can close it
                coro.close()
            return None
        mock_loop.run_until_complete.side_effect = run_until_complete
        mock_new_loop.return_value = mock_loop

        mock_deployment = MagicMock()
        mock_deployment._container_name = "swecli-runtime-12345678"
        mock_deployment.start = AsyncMock()
        mock_deployment.stop = AsyncMock()
        mock_deployment.runtime.run = AsyncMock()
        mock_deployment_cls.return_value = mock_deployment

        spec = SubAgentSpec(
            name="test-agent",
            description="Test",
            system_prompt="Prompt",
            docker_config=MagicMock(image="test-image")
        )

        deps = MagicMock(spec=SubAgentDeps)

        executor.manager.execute_subagent.return_value = {"success": True, "content": "Done"}

        # Run execution
        result = executor.execute(
            name="test-agent",
            task="Do something",
            deps=deps,
            spec=spec
        )

        assert result["success"] is True
        mock_deployment.start.assert_called_once()
        executor.manager.execute_subagent.assert_called_once()
        # Verify execute_subagent was called with docker_handler
        _, kwargs = executor.manager.execute_subagent.call_args
        assert "docker_handler" in kwargs
        mock_deployment.stop.assert_called_once()

    def test_execute_no_docker_config(self, executor):
        spec = SubAgentSpec(
            name="test-agent",
            description="Test",
            system_prompt="Prompt"
        )
        # No docker_config

        result = executor.execute(
            name="test-agent",
            task="Do something",
            deps=MagicMock(),
            spec=spec
        )

        assert result["success"] is False
        assert "No docker_config" in result["error"]
