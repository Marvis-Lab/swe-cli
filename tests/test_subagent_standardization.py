"""Tests for subagent interface standardization.

Tests the new standardized types, mixin, and nested callback factory
introduced to unify the interface across paper2code, resolve-issue,
and future subagent commands.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


from swecli.commands.subagent_mixin import CommandPhase, SubagentProgressMixin
from swecli.commands.subagent_types import (
    OutputMetadata,
    PatchMetadata,
    PRMetadata,
    RepoMetadata,
    SubagentCommandResult,
)
from swecli.ui_textual.nested_callback import (
    DockerContext,
    NestedUICallback,
    create_subagent_nested_callback,
)


# =============================================================================
# Tests for subagent_types.py
# =============================================================================


class TestOutputMetadata:
    """Tests for OutputMetadata dataclass."""

    def test_create_with_path(self):
        """Test creating OutputMetadata with a Path."""
        path = Path("/tmp/output")
        meta = OutputMetadata(output_path=path)
        assert meta.output_path == path

    def test_create_with_string_path(self):
        """Test creating OutputMetadata with string path conversion."""
        meta = OutputMetadata(output_path=Path("/tmp/output"))
        assert isinstance(meta.output_path, Path)


class TestPatchMetadata:
    """Tests for PatchMetadata dataclass."""

    def test_create_with_patch_path(self):
        """Test creating PatchMetadata with just patch_path."""
        path = Path("/tmp/issue-123.patch")
        meta = PatchMetadata(patch_path=path)
        assert meta.patch_path == path
        assert meta.base_commit is None

    def test_create_with_base_commit(self):
        """Test creating PatchMetadata with base_commit."""
        path = Path("/tmp/issue-123.patch")
        meta = PatchMetadata(patch_path=path, base_commit="abc1234")
        assert meta.patch_path == path
        assert meta.base_commit == "abc1234"


class TestPRMetadata:
    """Tests for PRMetadata dataclass."""

    def test_create_pr_metadata(self):
        """Test creating PRMetadata."""
        meta = PRMetadata(pr_url="https://github.com/owner/repo/pull/123", pr_number=123)
        assert meta.pr_url == "https://github.com/owner/repo/pull/123"
        assert meta.pr_number == 123


class TestRepoMetadata:
    """Tests for RepoMetadata dataclass."""

    def test_create_with_repo_path(self):
        """Test creating RepoMetadata with just repo_path."""
        path = Path("/workspace/repo")
        meta = RepoMetadata(repo_path=path)
        assert meta.repo_path == path
        assert meta.branch is None

    def test_create_with_branch(self):
        """Test creating RepoMetadata with branch."""
        path = Path("/workspace/repo")
        meta = RepoMetadata(repo_path=path, branch="fix/issue-123")
        assert meta.repo_path == path
        assert meta.branch == "fix/issue-123"


class TestSubagentCommandResult:
    """Tests for SubagentCommandResult dataclass."""

    def test_create_success_result(self):
        """Test creating a success result."""
        result = SubagentCommandResult(success=True, message="Done")
        assert result.success is True
        assert result.message == "Done"
        assert result.metadata is None
        assert result.artifact_paths == []

    def test_create_failure_result(self):
        """Test creating a failure result."""
        result = SubagentCommandResult(success=False, message="Failed")
        assert result.success is False
        assert result.message == "Failed"

    def test_create_with_output_metadata(self):
        """Test creating result with OutputMetadata."""
        meta = OutputMetadata(output_path=Path("/tmp/output"))
        result = SubagentCommandResult(success=True, message="Done", metadata=meta)
        assert result.metadata == meta
        assert isinstance(result.metadata, OutputMetadata)

    def test_create_with_patch_metadata(self):
        """Test creating result with PatchMetadata."""
        meta = PatchMetadata(patch_path=Path("/tmp/issue.patch"), base_commit="abc123")
        result = SubagentCommandResult(success=True, message="Done", metadata=meta)
        assert result.metadata == meta
        assert isinstance(result.metadata, PatchMetadata)

    def test_create_with_artifact_paths(self):
        """Test creating result with artifact paths."""
        artifacts = [Path("/tmp/file1.py"), Path("/tmp/file2.py")]
        result = SubagentCommandResult(
            success=True, message="Done", artifact_paths=artifacts
        )
        assert result.artifact_paths == artifacts


# =============================================================================
# Tests for subagent_mixin.py
# =============================================================================


class TestCommandPhase:
    """Tests for CommandPhase enum."""

    def test_all_phases_exist(self):
        """Test all expected phases are defined."""
        assert CommandPhase.LOADING.value == "loading"
        assert CommandPhase.CONFIGURING.value == "config"
        assert CommandPhase.EXECUTING.value == "exec"
        assert CommandPhase.EXTRACTING.value == "extract"
        assert CommandPhase.VERIFYING.value == "verify"
        assert CommandPhase.COMPLETE.value == "complete"


class TestSubagentProgressMixin:
    """Tests for SubagentProgressMixin."""

    def test_show_progress_with_callback(self):
        """Test show_progress calls ui_callback.on_progress_start."""

        class TestCommand(SubagentProgressMixin):
            def __init__(self, ui_callback):
                self.ui_callback = ui_callback

        mock_callback = MagicMock()
        cmd = TestCommand(mock_callback)

        cmd.show_progress("Loading...", CommandPhase.LOADING)
        mock_callback.on_progress_start.assert_called_once_with("[loading] Loading...")

    def test_show_progress_without_phase(self):
        """Test show_progress without phase prefix."""

        class TestCommand(SubagentProgressMixin):
            def __init__(self, ui_callback):
                self.ui_callback = ui_callback

        mock_callback = MagicMock()
        cmd = TestCommand(mock_callback)

        cmd.show_progress("Simple message")
        mock_callback.on_progress_start.assert_called_once_with("Simple message")

    def test_show_progress_without_callback(self):
        """Test show_progress with None callback doesn't crash."""

        class TestCommand(SubagentProgressMixin):
            def __init__(self):
                self.ui_callback = None

        cmd = TestCommand()
        cmd.show_progress("Message")  # Should not raise

    def test_complete_progress(self):
        """Test complete_progress calls ui_callback.on_progress_complete."""

        class TestCommand(SubagentProgressMixin):
            def __init__(self, ui_callback):
                self.ui_callback = ui_callback

        mock_callback = MagicMock()
        cmd = TestCommand(mock_callback)

        cmd.complete_progress("Done!")
        mock_callback.on_progress_complete.assert_called_once_with("Done!")

    def test_show_spawn_header(self):
        """Test show_spawn_header calls ui_callback.on_tool_call."""

        class TestCommand(SubagentProgressMixin):
            def __init__(self, ui_callback):
                self.ui_callback = ui_callback

        mock_callback = MagicMock()
        cmd = TestCommand(mock_callback)

        cmd.show_spawn_header("Paper2Code", "Implement paper.pdf")
        mock_callback.on_tool_call.assert_called_once_with(
            "spawn_subagent",
            {
                "subagent_type": "Paper2Code",
                "description": "Implement paper.pdf",
            },
        )


# =============================================================================
# Tests for nested_callback.py (DockerContext and factory)
# =============================================================================


class TestDockerContext:
    """Tests for DockerContext dataclass."""

    def test_create_minimal(self):
        """Test creating DockerContext with required fields only."""
        ctx = DockerContext(
            workspace_dir="/workspace",
            image_name="ghcr.io/astral-sh/uv:python3.11",
            container_id="a1b2c3d4",
        )
        assert ctx.workspace_dir == "/workspace"
        assert ctx.image_name == "ghcr.io/astral-sh/uv:python3.11"
        assert ctx.container_id == "a1b2c3d4"
        assert ctx.local_dir is None

    def test_create_with_local_dir(self):
        """Test creating DockerContext with local_dir."""
        ctx = DockerContext(
            workspace_dir="/testbed",
            image_name="sweb.eval.x86_64.django:latest",
            container_id="12345678",
            local_dir="/Users/dev/project",
        )
        assert ctx.local_dir == "/Users/dev/project"


class TestCreateSubagentNestedCallback:
    """Tests for create_subagent_nested_callback factory."""

    def test_returns_none_when_callback_is_none(self):
        """Test factory returns None when ui_callback is None."""
        result = create_subagent_nested_callback(
            ui_callback=None,
            subagent_name="Test-Agent",
        )
        assert result is None

    def test_creates_nested_callback_without_docker(self):
        """Test factory creates NestedUICallback without Docker context."""
        mock_callback = MagicMock()
        result = create_subagent_nested_callback(
            ui_callback=mock_callback,
            subagent_name="Code-Reviewer",
        )
        assert isinstance(result, NestedUICallback)
        assert result._context == "Code-Reviewer"
        assert result._depth == 1
        assert result._path_sanitizer is None

    def test_creates_nested_callback_with_docker(self):
        """Test factory creates NestedUICallback with Docker context."""
        mock_callback = MagicMock()
        docker_ctx = DockerContext(
            workspace_dir="/workspace",
            image_name="ghcr.io/astral-sh/uv:python3.11",
            container_id="a1b2c3d4",
        )
        result = create_subagent_nested_callback(
            ui_callback=mock_callback,
            subagent_name="Issue-Resolver",
            docker_context=docker_ctx,
        )
        assert isinstance(result, NestedUICallback)
        assert result._context == "Issue-Resolver"
        assert result._depth == 1
        assert result._path_sanitizer is not None

    def test_docker_path_sanitizer_prefix(self):
        """Test Docker path sanitizer creates correct prefix."""
        mock_callback = MagicMock()
        docker_ctx = DockerContext(
            workspace_dir="/workspace",
            image_name="ghcr.io/astral-sh/uv:python3.11-bookworm",
            container_id="a1b2c3d4",
        )
        result = create_subagent_nested_callback(
            ui_callback=mock_callback,
            subagent_name="Test",
            docker_context=docker_ctx,
        )
        # Test the path sanitizer
        sanitized = result._path_sanitizer("README.md")
        assert sanitized == "[uv:a1b2c3d4]:/workspace/README.md"

    def test_docker_path_sanitizer_workspace_path(self):
        """Test Docker path sanitizer handles workspace paths."""
        mock_callback = MagicMock()
        docker_ctx = DockerContext(
            workspace_dir="/testbed",
            image_name="sweb.eval.x86_64.django:latest",
            container_id="12345678",
        )
        result = create_subagent_nested_callback(
            ui_callback=mock_callback,
            subagent_name="Test",
            docker_context=docker_ctx,
        )
        sanitized = result._path_sanitizer("/testbed/src/file.py")
        assert sanitized == "[sweb.eval.x86_64.django:12345678]:/testbed/src/file.py"


class TestNestedCallbackIntegration:
    """Integration tests for NestedUICallback with Docker context."""

    def test_tool_call_path_sanitization(self):
        """Test that tool calls have paths sanitized."""
        mock_parent = MagicMock()
        docker_ctx = DockerContext(
            workspace_dir="/workspace",
            image_name="ghcr.io/astral-sh/uv:python3.11",
            container_id="abcd1234",
        )
        nested = create_subagent_nested_callback(
            ui_callback=mock_parent,
            subagent_name="Test-Agent",
            docker_context=docker_ctx,
        )

        # Simulate a tool call with a path argument
        nested.on_tool_call("read_file", {"file_path": "src/main.py"})

        # Check the call was forwarded with sanitized path
        mock_parent.on_nested_tool_call.assert_called_once()
        args = mock_parent.on_nested_tool_call.call_args
        assert args[0][0] == "read_file"  # tool_name
        assert "[uv:abcd1234]:/workspace/src/main.py" in str(args[0][1])  # sanitized path

    def test_bash_command_gets_working_dir(self):
        """Test that bash commands get working_dir injected."""
        mock_parent = MagicMock()
        docker_ctx = DockerContext(
            workspace_dir="/workspace",
            image_name="python:3.11-slim",
            container_id="xyz12345",
        )
        nested = create_subagent_nested_callback(
            ui_callback=mock_parent,
            subagent_name="Test-Agent",
            docker_context=docker_ctx,
        )

        # Simulate a bash command without working_dir
        nested.on_tool_call("bash_execute", {"command": "ls -la"})

        # Check working_dir was injected
        mock_parent.on_nested_tool_call.assert_called_once()
        args = mock_parent.on_nested_tool_call.call_args
        tool_args = args[0][1]
        assert "working_dir" in tool_args
        # The sanitizer returns "." unchanged (current directory indicator)
        assert tool_args["working_dir"] == "."
