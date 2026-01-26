"""Quality gates for Ralph - runs typecheck, lint, and tests before commits."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class ProjectType(Enum):
    """Detected project type."""

    PYTHON = "python"
    NODE = "node"
    UNKNOWN = "unknown"


@dataclass
class QualityGateResult:
    """Result of running quality gates."""

    success: bool
    typecheck_passed: Optional[bool] = None
    typecheck_output: str = ""
    lint_passed: Optional[bool] = None
    lint_output: str = ""
    tests_passed: Optional[bool] = None
    tests_output: str = ""
    errors: list[str] = field(default_factory=list)

    def get_summary(self) -> str:
        """Get a human-readable summary of the results."""
        lines = []

        if self.typecheck_passed is not None:
            status = "PASS" if self.typecheck_passed else "FAIL"
            lines.append(f"Typecheck: {status}")

        if self.lint_passed is not None:
            status = "PASS" if self.lint_passed else "FAIL"
            lines.append(f"Lint: {status}")

        if self.tests_passed is not None:
            status = "PASS" if self.tests_passed else "FAIL"
            lines.append(f"Tests: {status}")

        if self.errors:
            lines.append("\nErrors:")
            for error in self.errors:
                lines.append(f"  - {error}")

        return "\n".join(lines)


class QualityGateRunner:
    """Runs quality gates for a project.

    Auto-detects project type and runs appropriate checks:
    - Python: mypy, ruff/black, pytest
    - Node: tsc, eslint, jest/vitest
    """

    def __init__(self, working_dir: Path, timeout: int = 120):
        """Initialize the runner.

        Args:
            working_dir: Project working directory
            timeout: Timeout in seconds for each command
        """
        self.working_dir = working_dir
        self.timeout = timeout
        self._project_type: Optional[ProjectType] = None

    def detect_project_type(self) -> ProjectType:
        """Detect the project type based on config files.

        Returns:
            Detected ProjectType
        """
        if self._project_type is not None:
            return self._project_type

        # Check for Python
        if (self.working_dir / "pyproject.toml").exists() or (
            self.working_dir / "setup.py"
        ).exists():
            self._project_type = ProjectType.PYTHON
        # Check for Node
        elif (self.working_dir / "package.json").exists():
            self._project_type = ProjectType.NODE
        else:
            self._project_type = ProjectType.UNKNOWN

        return self._project_type

    def run_all(self, skip_tests: bool = False) -> QualityGateResult:
        """Run all quality gates.

        Args:
            skip_tests: If True, skip running tests (useful for quick checks)

        Returns:
            QualityGateResult with all check results
        """
        project_type = self.detect_project_type()

        if project_type == ProjectType.PYTHON:
            return self._run_python_gates(skip_tests)
        elif project_type == ProjectType.NODE:
            return self._run_node_gates(skip_tests)
        else:
            return QualityGateResult(
                success=True, errors=["Unknown project type - skipping quality gates"]
            )

    def _run_command(self, cmd: list[str], description: str) -> tuple[bool, str]:
        """Run a command and return success status and output.

        Args:
            cmd: Command to run
            description: Description for error messages

        Returns:
            Tuple of (success, output)
        """
        try:
            result = subprocess.run(
                cmd,
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, f"{description} timed out after {self.timeout}s"
        except FileNotFoundError:
            return True, f"{description} command not found - skipping"
        except Exception as e:
            return False, f"{description} failed: {str(e)}"

    def _run_python_gates(self, skip_tests: bool = False) -> QualityGateResult:
        """Run Python quality gates.

        Args:
            skip_tests: If True, skip pytest

        Returns:
            QualityGateResult
        """
        result = QualityGateResult(success=True)
        errors = []

        # Check for uv or regular python tools
        has_uv = (self.working_dir / "uv.lock").exists() or self._command_exists("uv")

        # Typecheck with mypy
        if has_uv:
            typecheck_cmd = ["uv", "run", "mypy", "swecli/"]
        else:
            typecheck_cmd = ["mypy", "swecli/"]

        result.typecheck_passed, result.typecheck_output = self._run_command(
            typecheck_cmd, "Typecheck"
        )
        if not result.typecheck_passed and "command not found" not in result.typecheck_output:
            errors.append("Typecheck failed")

        # Lint with ruff
        if has_uv:
            lint_cmd = ["uv", "run", "ruff", "check", "swecli/"]
        else:
            lint_cmd = ["ruff", "check", "swecli/"]

        result.lint_passed, result.lint_output = self._run_command(lint_cmd, "Lint")
        if not result.lint_passed and "command not found" not in result.lint_output:
            errors.append("Lint failed")

        # Tests with pytest
        if not skip_tests:
            if has_uv:
                test_cmd = ["uv", "run", "pytest", "-x", "--tb=short"]
            else:
                test_cmd = ["pytest", "-x", "--tb=short"]

            result.tests_passed, result.tests_output = self._run_command(test_cmd, "Tests")
            if not result.tests_passed and "command not found" not in result.tests_output:
                errors.append("Tests failed")

        result.errors = errors
        result.success = len(errors) == 0

        return result

    def _run_node_gates(self, skip_tests: bool = False) -> QualityGateResult:
        """Run Node.js quality gates.

        Args:
            skip_tests: If True, skip tests

        Returns:
            QualityGateResult
        """
        result = QualityGateResult(success=True)
        errors = []

        # Detect package manager
        if (self.working_dir / "pnpm-lock.yaml").exists():
            pm = "pnpm"
        elif (self.working_dir / "yarn.lock").exists():
            pm = "yarn"
        else:
            pm = "npm"

        # Typecheck with tsc
        typecheck_cmd = [pm, "run", "typecheck"] if pm != "npm" else ["npm", "run", "typecheck"]
        result.typecheck_passed, result.typecheck_output = self._run_command(
            typecheck_cmd, "Typecheck"
        )
        if not result.typecheck_passed:
            # Try direct tsc if npm script doesn't exist
            tsc_cmd = ["npx", "tsc", "--noEmit"]
            result.typecheck_passed, result.typecheck_output = self._run_command(
                tsc_cmd, "Typecheck"
            )
            if not result.typecheck_passed and "command not found" not in result.typecheck_output:
                errors.append("Typecheck failed")

        # Lint with eslint
        lint_cmd = [pm, "run", "lint"] if pm != "npm" else ["npm", "run", "lint"]
        result.lint_passed, result.lint_output = self._run_command(lint_cmd, "Lint")
        if not result.lint_passed and "command not found" not in result.lint_output:
            # Try direct eslint
            eslint_cmd = ["npx", "eslint", ".", "--ext", ".ts,.tsx,.js,.jsx"]
            result.lint_passed, result.lint_output = self._run_command(eslint_cmd, "Lint")
            if not result.lint_passed:
                errors.append("Lint failed")

        # Tests
        if not skip_tests:
            test_cmd = [pm, "run", "test"] if pm != "npm" else ["npm", "run", "test"]
            result.tests_passed, result.tests_output = self._run_command(test_cmd, "Tests")
            if not result.tests_passed and "command not found" not in result.tests_output:
                errors.append("Tests failed")

        result.errors = errors
        result.success = len(errors) == 0

        return result

    def _command_exists(self, cmd: str) -> bool:
        """Check if a command exists in PATH.

        Args:
            cmd: Command name to check

        Returns:
            True if command exists
        """
        try:
            subprocess.run(
                ["which", cmd], capture_output=True, check=True, timeout=5
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False
