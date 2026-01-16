"""Tests for DockerSubAgentExecutor."""

import pytest
from unittest.mock import MagicMock, patch, ANY
from pathlib import Path
from swecli.core.agents.subagents.docker_execution import DockerSubAgentExecutor

@pytest.fixture
def mock_manager():
    manager = MagicMock()
    manager._working_dir = Path("/local/work")
    return manager

@pytest.fixture
def executor(mock_manager):
    return DockerSubAgentExecutor(mock_manager)

class TestDockerExecution:
    def test_init(self, mock_manager):
        executor = DockerSubAgentExecutor(mock_manager)
        assert executor.manager == mock_manager

    @patch("shutil.which")
    def test_is_docker_available(self, mock_which, executor):
        mock_which.return_value = "/usr/bin/docker"
        assert executor.is_docker_available() is True

        mock_which.return_value = None
        assert executor.is_docker_available() is False

    def test_extract_input_files(self, executor, tmp_path):
        # Setup temporary files
        (tmp_path / "paper.pdf").touch()
        (tmp_path / "data.csv").touch()
        (tmp_path / "test.docx").touch()

        task = "Read @paper.pdf and analyze data.csv. Also check test.docx"

        files = executor.extract_input_files(task, tmp_path)

        filenames = [f.name for f in files]
        assert "paper.pdf" in filenames
        assert "test.docx" in filenames
        assert "data.csv" not in filenames  # Should not extract CSV

    def test_extract_github_info(self, executor):
        task = "Fix issue https://github.com/owner/repo/issues/123 please"
        result = executor.extract_github_info(task)

        assert result is not None
        repo_url, owner_repo, issue_number = result
        assert repo_url == "https://github.com/owner/repo.git"
        assert owner_repo == "owner/repo"
        assert issue_number == "123"

    def test_rewrite_task_for_docker(self, executor):
        input_files = [Path("/local/work/paper.pdf")]
        workspace_dir = "/workspace"
        task = "Read @paper.pdf located in this repo"

        rewritten = executor.rewrite_task_for_docker(task, input_files, workspace_dir)

        assert "/workspace/paper.pdf" in rewritten
        assert "in /workspace" in rewritten
        assert "CRITICAL: Docker Environment" in rewritten

    def test_create_docker_path_sanitizer(self, executor):
        sanitizer = executor._create_docker_path_sanitizer(
            workspace_dir="/workspace",
            local_dir="/local/work",
            image_name="ghcr.io/astral-sh/uv:python3.11",
            container_id="a1b2c3d4"
        )

        # Test local path mapping
        assert sanitizer("/local/work/src/main.py") == "[uv:a1b2c3d4]:/workspace/src/main.py"

        # Test direct workspace path
        assert sanitizer("/workspace/README.md") == "[uv:a1b2c3d4]:/workspace/README.md"

        # Test relative path
        assert sanitizer("src/test.py") == "[uv:a1b2c3d4]:/workspace/src/test.py"

    @patch("swecli.ui_textual.nested_callback.NestedUICallback")
    def test_create_docker_nested_callback(self, mock_nested, executor):
        ui_callback = MagicMock()

        result = executor.create_docker_nested_callback(
            ui_callback=ui_callback,
            subagent_name="TestAgent",
            workspace_dir="/workspace",
            image_name="image",
            container_id="123",
        )

        assert result is not None
        mock_nested.assert_called_once()
        call_kwargs = mock_nested.call_args[1]
        assert call_kwargs["parent_callback"] == ui_callback
        assert call_kwargs["parent_context"] == "TestAgent"
        assert "path_sanitizer" in call_kwargs

    def test_extract_task_description(self, executor):
        task = "Implement paper.pdf\nSome details"
        assert executor.extract_task_description(task) == "Implement paper.pdf"

        task = "Do something\nWith details"
        assert executor.extract_task_description(task) == "Do something"

        long_task = "A" * 60
        assert executor.extract_task_description(long_task).endswith("...")

    @patch("subprocess.run")
    def test_copy_files_to_docker(self, mock_run, executor):
        mock_run.return_value.returncode = 0

        files = [Path("test.py")]
        mapping = executor.copy_files_to_docker("container", files, "/workspace")

        assert "/workspace/test.py" in mapping
        assert mapping["/workspace/test.py"] == "test.py"
        mock_run.assert_called_once()

    @patch("swecli.core.docker.tool_handler.DockerToolHandler")
    @patch("swecli.core.docker.deployment.DockerDeployment")
    def test_execute_with_docker(self, MockDeployment, MockHandler, executor):
        # Setup mocks
        deployment = MockDeployment.return_value
        deployment._container_name = "swecli-runtime-12345678"
        deployment.start = MagicMock()
        deployment.stop = MagicMock()
        deployment.runtime.run = MagicMock()

        deps = MagicMock()
        spec = {
            "docker_config": MagicMock(image="test-image"),
            "copy_back_recursive": False
        }

        executor.manager.execute_subagent.return_value = {"success": True, "content": "Done"}

        with patch("asyncio.new_event_loop") as mock_new_loop, \
             patch("asyncio.set_event_loop") as mock_set_loop:

            loop = MagicMock()
            mock_new_loop.return_value = loop

            result = executor.execute_with_docker(
                name="TestAgent",
                task="Do task",
                deps=deps,
                spec=spec,
                show_spawn_header=False
            )

            # Print error if failed
            if not result.get("success"):
                print(f"Error: {result.get('error')}")

            assert result["success"] is True
            assert deployment.start.called
            assert deployment.stop.called
            executor.manager.execute_subagent.assert_called_once()
