"""Utilities for extracting patches from git repositories."""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional


def _run_git_safe(args: list[str], cwd: Path, timeout: int = 30) -> Optional[subprocess.CompletedProcess]:
    """Run git command in a thread pool to avoid Textual FD issues.

    Args:
        args: Git command arguments
        cwd: Working directory
        timeout: Timeout in seconds

    Returns:
        CompletedProcess or None on error
    """

    def _run():
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            return future.result(timeout=timeout + 5)
    except Exception:
        return None


def extract_patch(repo_dir: Path, base_branch: str = "main") -> str:
    """Extract unified diff from committed changes.

    Args:
        repo_dir: Path to the git repository
        base_branch: The base branch to diff against (default: "main")

    Returns:
        Unified diff string (empty if no changes or error)
    """
    # First, try to get the remote tracking branch
    # This handles cases where the base branch might be origin/main
    # Get the merge base between the current HEAD and the base branch
    merge_base_result = _run_git_safe(
        ["git", "merge-base", base_branch, "HEAD"],
        cwd=repo_dir,
    )

    if merge_base_result and merge_base_result.returncode == 0:
        merge_base = merge_base_result.stdout.strip()
        # Diff from merge base to HEAD
        diff_result = _run_git_safe(
            ["git", "diff", merge_base, "HEAD"],
            cwd=repo_dir,
        )
        if diff_result and diff_result.returncode == 0:
            return diff_result.stdout

    # Fallback: try direct diff with three-dot notation
    result = _run_git_safe(
        ["git", "diff", f"{base_branch}...HEAD"],
        cwd=repo_dir,
    )
    if result and result.returncode == 0:
        return result.stdout

    # Final fallback: diff from initial commit
    # Get all commits, diff from first to last
    result = _run_git_safe(
        ["git", "diff", "HEAD~1", "HEAD"],
        cwd=repo_dir,
    )
    if result and result.returncode == 0:
        return result.stdout

    return ""


def get_base_branch(repo_dir: Path) -> str:
    """Detect the default branch name (main or master).

    Args:
        repo_dir: Path to the git repository

    Returns:
        Branch name ("main" or "master", defaults to "main")
    """
    # Check if origin/main exists
    result = _run_git_safe(
        ["git", "rev-parse", "--verify", "origin/main"],
        cwd=repo_dir,
    )
    if result and result.returncode == 0:
        return "origin/main"

    # Check if origin/master exists
    result = _run_git_safe(
        ["git", "rev-parse", "--verify", "origin/master"],
        cwd=repo_dir,
    )
    if result and result.returncode == 0:
        return "origin/master"

    # Check local main
    result = _run_git_safe(
        ["git", "rev-parse", "--verify", "main"],
        cwd=repo_dir,
    )
    if result and result.returncode == 0:
        return "main"

    # Check local master
    result = _run_git_safe(
        ["git", "rev-parse", "--verify", "master"],
        cwd=repo_dir,
    )
    if result and result.returncode == 0:
        return "master"

    return "main"  # Default fallback
