"""Tests for Ralph orchestrator."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from swecli.ralph.orchestrator import (
    RalphOrchestrator,
    RalphConfig,
    ApprovalMode,
    IterationResult,
)
from swecli.ralph.models.prd import RalphPRD, UserStory


class TestRalphConfig:
    """Tests for RalphConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RalphConfig()

        assert config.max_iterations == 10
        assert config.approval_mode == ApprovalMode.AUTO
        assert config.skip_tests is False
        assert config.auto_commit is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = RalphConfig(
            max_iterations=5,
            approval_mode=ApprovalMode.PER_STORY,
            skip_tests=True,
            auto_commit=False,
        )

        assert config.max_iterations == 5
        assert config.approval_mode == ApprovalMode.PER_STORY
        assert config.skip_tests is True
        assert config.auto_commit is False


class TestRalphOrchestrator:
    """Tests for RalphOrchestrator."""

    @pytest.fixture
    def sample_prd(self, tmp_path):
        """Create a sample PRD file."""
        prd = RalphPRD(
            project="TestProject",
            branch_name="ralph/test",
            description="Test project",
            user_stories=[
                UserStory(
                    id="US-001",
                    title="First Story",
                    description="Test",
                    acceptance_criteria=["A"],
                    priority=1,
                    passes=False,
                ),
            ],
        )
        prd_path = tmp_path / "prd.json"
        prd.save(prd_path)
        return prd_path

    @pytest.fixture
    def orchestrator(self, tmp_path, sample_prd):
        """Create an orchestrator instance."""
        config = RalphConfig(
            max_iterations=3,
            prd_path=Path("prd.json"),
        )
        return RalphOrchestrator(
            working_dir=tmp_path,
            config=config,
        )

    def test_get_status_no_prd(self, tmp_path):
        """Test status when no PRD exists."""
        config = RalphConfig()
        orchestrator = RalphOrchestrator(tmp_path, config)

        status = orchestrator.get_status()
        assert "No PRD found" in status

    def test_get_status_with_prd(self, orchestrator):
        """Test status with existing PRD."""
        status = orchestrator.get_status()

        assert "TestProject" in status
        assert "US-001" in status

    @patch("subprocess.run")
    def test_ensure_branch_already_on_branch(self, mock_run, orchestrator):
        """Test when already on correct branch."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="ralph/test\n",
            stderr="",
        )

        result = orchestrator._ensure_branch("ralph/test")
        assert result is True

    @patch("subprocess.run")
    def test_ensure_branch_checkout_existing(self, mock_run, orchestrator):
        """Test checking out existing branch."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="main\n", stderr=""),  # Current branch
            MagicMock(returncode=0, stdout="", stderr=""),  # Checkout
        ]

        result = orchestrator._ensure_branch("ralph/test")
        assert result is True

    @patch("subprocess.run")
    def test_commit_changes(self, mock_run, orchestrator):
        """Test committing changes."""
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add
            MagicMock(returncode=1),  # git diff (has changes)
            MagicMock(returncode=0),  # git commit
        ]

        result = orchestrator._commit_changes("US-001", "Test Story")
        assert result is True

    @patch("subprocess.run")
    def test_commit_no_changes(self, mock_run, orchestrator):
        """Test commit when no changes."""
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add
            MagicMock(returncode=0),  # git diff (no changes)
        ]

        result = orchestrator._commit_changes("US-001", "Test Story")
        assert result is True  # No error, just nothing to commit

    def test_iteration_result_structure(self):
        """Test IterationResult dataclass."""
        result = IterationResult(
            iteration=1,
            story_id="US-001",
            success=True,
            committed=True,
        )

        assert result.iteration == 1
        assert result.success is True
        assert result.error is None
