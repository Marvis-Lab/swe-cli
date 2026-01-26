"""Tests for Ralph quality gates."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from swecli.ralph.quality.gates import (
    QualityGateRunner,
    QualityGateResult,
    ProjectType,
)


class TestQualityGateResult:
    """Tests for QualityGateResult."""

    def test_success_result(self):
        """Test creating a successful result."""
        result = QualityGateResult(
            success=True,
            typecheck_passed=True,
            lint_passed=True,
            tests_passed=True,
        )

        assert result.success is True
        assert len(result.errors) == 0

    def test_failure_result(self):
        """Test creating a failed result."""
        result = QualityGateResult(
            success=False,
            typecheck_passed=False,
            typecheck_output="Type error in foo.py",
            errors=["Typecheck failed"],
        )

        assert result.success is False
        assert "Typecheck failed" in result.errors

    def test_get_summary(self):
        """Test generating result summary."""
        result = QualityGateResult(
            success=False,
            typecheck_passed=True,
            lint_passed=False,
            tests_passed=True,
            errors=["Lint failed"],
        )

        summary = result.get_summary()
        assert "Typecheck: PASS" in summary
        assert "Lint: FAIL" in summary
        assert "Tests: PASS" in summary
        assert "Lint failed" in summary


class TestQualityGateRunner:
    """Tests for QualityGateRunner."""

    @pytest.fixture
    def python_project(self, tmp_path):
        """Create a Python project structure."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")
        (tmp_path / "swecli").mkdir()
        (tmp_path / "swecli" / "__init__.py").touch()
        return tmp_path

    @pytest.fixture
    def node_project(self, tmp_path):
        """Create a Node.js project structure."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        return tmp_path

    def test_detect_python_project(self, python_project):
        """Test detecting Python project."""
        runner = QualityGateRunner(python_project)
        assert runner.detect_project_type() == ProjectType.PYTHON

    def test_detect_node_project(self, node_project):
        """Test detecting Node.js project."""
        runner = QualityGateRunner(node_project)
        assert runner.detect_project_type() == ProjectType.NODE

    def test_detect_unknown_project(self, tmp_path):
        """Test detecting unknown project type."""
        runner = QualityGateRunner(tmp_path)
        assert runner.detect_project_type() == ProjectType.UNKNOWN

    @patch("subprocess.run")
    def test_run_python_gates_success(self, mock_run, python_project):
        """Test running Python gates successfully."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )

        runner = QualityGateRunner(python_project)
        result = runner.run_all()

        assert result.success is True
        assert result.typecheck_passed is True
        assert result.lint_passed is True

    @patch("subprocess.run")
    def test_run_python_gates_typecheck_fail(self, mock_run, python_project):
        """Test Python gates with typecheck failure."""
        def mock_subprocess(cmd, **kwargs):
            if "mypy" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="Type error")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = mock_subprocess

        runner = QualityGateRunner(python_project)
        result = runner.run_all()

        assert result.success is False
        assert result.typecheck_passed is False
        assert "Typecheck failed" in result.errors

    @patch("subprocess.run")
    def test_run_node_gates_success(self, mock_run, node_project):
        """Test running Node.js gates successfully."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )

        runner = QualityGateRunner(node_project)
        result = runner.run_all()

        assert result.success is True

    def test_run_unknown_project_skips(self, tmp_path):
        """Test that unknown project type skips gates."""
        runner = QualityGateRunner(tmp_path)
        result = runner.run_all()

        assert result.success is True
        assert "Unknown project type" in result.errors[0]

    @patch("subprocess.run")
    def test_skip_tests_option(self, mock_run, python_project):
        """Test that skip_tests option works."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )

        runner = QualityGateRunner(python_project)
        result = runner.run_all(skip_tests=True)

        assert result.success is True
        assert result.tests_passed is None  # Not run

    @patch("subprocess.run")
    def test_timeout_handling(self, mock_run, python_project):
        """Test handling of command timeout."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)

        runner = QualityGateRunner(python_project, timeout=10)
        result = runner.run_all()

        # Should handle timeout gracefully
        assert "timed out" in result.typecheck_output
