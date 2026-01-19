"""Local git operations for issue resolver."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from swecli.core.paths import get_paths


@dataclass
class CloneResult:
    """Result of repository clone operation."""

    success: bool
    repo_path: Optional[Path] = None
    error: Optional[str] = None


@dataclass
class TestResult:
    """Result of running tests."""

    success: Optional[bool]  # None means no test runner found
    command: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    message: str = ""


class GitHelper:
    """Local git operations helper."""

    def __init__(self, working_dir: Optional[Path] = None):
        """Initialize git helper.

        Args:
            working_dir: Base working directory for cloned repos
        """
        self.working_dir = working_dir or get_paths().global_repos_dir
        self.working_dir.mkdir(parents=True, exist_ok=True)

    def clone_repo(
        self,
        clone_url: str,
        owner: str,
        repo: str,
        issue_number: int,
        shallow: bool = True,
    ) -> CloneResult:
        """Clone repository to local directory.

        Args:
            clone_url: Git clone URL (HTTPS or SSH)
            owner: Repository owner (for directory naming)
            repo: Repository name (for directory naming)
            issue_number: Issue number (for directory naming)
            shallow: Whether to do a shallow clone (default True)

        Returns:
            CloneResult with repo path or error
        """
        repo_dir = self.working_dir / f"{owner}-{repo}-issue-{issue_number}"

        # Clean up existing directory if present
        if repo_dir.exists():
            try:
                shutil.rmtree(repo_dir)
            except OSError as e:
                return CloneResult(
                    success=False,
                    error=f"Failed to clean existing directory: {e}",
                )

        # Build clone command
        clone_cmd = ["git", "clone", clone_url, str(repo_dir)]
        if shallow:
            clone_cmd.extend(["--depth", "1"])

        try:
            result = subprocess.run(
                clone_cmd,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minutes for clone
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Clone failed"
                return CloneResult(success=False, error=error_msg)

            return CloneResult(success=True, repo_path=repo_dir)

        except subprocess.TimeoutExpired:
            # Clean up partial clone
            if repo_dir.exists():
                shutil.rmtree(repo_dir, ignore_errors=True)
            return CloneResult(
                success=False,
                error="Clone timed out after 2 minutes",
            )

    def create_branch(self, repo_path: Path, branch_name: str) -> bool:
        """Create and checkout a new branch.

        Args:
            repo_path: Path to repository
            branch_name: Name for new branch

        Returns:
            True if successful
        """
        try:
            result = subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def has_changes(self, repo_path: Path) -> bool:
        """Check if there are uncommitted changes.

        Args:
            repo_path: Path to repository

        Returns:
            True if there are changes to commit
        """
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return bool(result.stdout.strip())
        except subprocess.TimeoutExpired:
            return False

    def commit_changes(self, repo_path: Path, message: str) -> bool:
        """Stage all changes and create commit.

        Args:
            repo_path: Path to repository
            message: Commit message

        Returns:
            True if successful
        """
        try:
            # Stage all changes
            subprocess.run(
                ["git", "add", "-A"],
                cwd=repo_path,
                capture_output=True,
                timeout=10,
            )

            # Create commit
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def push_branch(self, repo_path: Path, remote: str = "origin") -> tuple[bool, str]:
        """Push the current branch to a remote.

        Args:
            repo_path: Path to repository
            remote: Remote name (default: origin)

        Returns:
            Tuple of (success, error_message)
        """
        try:
            result = subprocess.run(
                ["git", "push", "-u", remote, "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                return False, result.stderr.strip() or "Push failed"

            return True, ""

        except subprocess.TimeoutExpired:
            return False, "Push timed out"

    def get_diff(self, repo_path: Path) -> str:
        """Get the current diff of staged and unstaged changes.

        Args:
            repo_path: Path to repository

        Returns:
            Diff output as string
        """
        try:
            # Stage everything first to get complete diff
            subprocess.run(
                ["git", "add", "-A"],
                cwd=repo_path,
                capture_output=True,
                timeout=10,
            )

            result = subprocess.run(
                ["git", "diff", "--cached"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            return ""

    def get_current_branch(self, repo_path: Path) -> str:
        """Get the current branch name.

        Args:
            repo_path: Path to repository

        Returns:
            Current branch name
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else "HEAD"
        except subprocess.TimeoutExpired:
            return "HEAD"

    def get_default_branch(self, repo_path: Path) -> str:
        """Get the default branch name for the repository.

        Args:
            repo_path: Path to repository

        Returns:
            Default branch name (usually 'main' or 'master')
        """
        try:
            result = subprocess.run(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                # Output is like 'refs/remotes/origin/main'
                return result.stdout.strip().split("/")[-1]

            # Fallback: try common branch names
            for branch in ["main", "master"]:
                check = subprocess.run(
                    ["git", "rev-parse", "--verify", f"origin/{branch}"],
                    cwd=repo_path,
                    capture_output=True,
                    timeout=10,
                )
                if check.returncode == 0:
                    return branch

            return "main"  # Default fallback

        except subprocess.TimeoutExpired:
            return "main"

    def run_tests(self, repo_path: Path, timeout: int = 300) -> TestResult:
        """Attempt to run tests in the repository.

        Tries common test commands in order.

        Args:
            repo_path: Path to repository
            timeout: Timeout in seconds (default 5 minutes)

        Returns:
            TestResult with success status and output
        """
        # Common test commands to try
        test_commands = [
            # Python
            (["pytest", "--tb=short", "-q"], "pytest"),
            (["python", "-m", "pytest", "--tb=short", "-q"], "pytest"),
            (["python", "-m", "unittest", "discover"], "unittest"),
            # Node.js
            (["npm", "test"], "npm test"),
            (["yarn", "test"], "yarn test"),
            # Go
            (["go", "test", "./..."], "go test"),
            # Rust
            (["cargo", "test"], "cargo test"),
            # Make
            (["make", "test"], "make test"),
        ]

        for cmd, cmd_name in test_commands:
            try:
                result = subprocess.run(
                    cmd,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

                # Check if command exists (not "command not found")
                stderr_lower = result.stderr.lower()
                if "command not found" in stderr_lower or "not found" in stderr_lower:
                    continue

                # Command exists, return result
                return TestResult(
                    success=result.returncode == 0,
                    command=cmd_name,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exit_code=result.returncode,
                )

            except FileNotFoundError:
                # Command doesn't exist, try next
                continue
            except subprocess.TimeoutExpired:
                return TestResult(
                    success=False,
                    command=cmd_name,
                    message=f"Test timed out after {timeout} seconds",
                )

        # No test runner found
        return TestResult(
            success=None,
            message="No test runner detected",
        )

    def set_remote_url(self, repo_path: Path, remote_name: str, url: str) -> bool:
        """Set or update a remote URL.

        Args:
            repo_path: Path to repository
            remote_name: Name of remote (e.g., 'origin', 'upstream')
            url: New URL for the remote

        Returns:
            True if successful
        """
        try:
            # Try to set the URL (works if remote exists)
            result = subprocess.run(
                ["git", "remote", "set-url", remote_name, url],
                cwd=repo_path,
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True

            # Remote doesn't exist, add it
            result = subprocess.run(
                ["git", "remote", "add", remote_name, url],
                cwd=repo_path,
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0

        except subprocess.TimeoutExpired:
            return False
