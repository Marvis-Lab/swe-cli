"""Repository setup utilities for SWE-bench instances."""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _run_git_in_thread(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = 120,
) -> tuple[int, str, str]:
    """Run git command in a thread to isolate from Textual's file descriptors.

    Returns:
        (returncode, stdout, stderr) tuple
    """
    import os

    kwargs: dict = {
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "close_fds": True,
    }

    if os.name != "nt":
        kwargs["start_new_session"] = True

    result = subprocess.run(args, timeout=timeout, **kwargs)
    return result.returncode, result.stdout, result.stderr


def _run_git(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    """Run a git command with proper file descriptor handling.

    Runs in a separate thread to avoid 'bad value(s) in fds_to_keep' errors
    that occur when subprocess is called from within Textual's event loop.
    """
    # Run in thread pool to isolate from parent's file descriptors
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_git_in_thread, args, cwd, timeout)
        returncode, stdout, stderr = future.result(timeout=timeout + 10)

    # Create a CompletedProcess-like result
    result = subprocess.CompletedProcess(args, returncode, stdout, stderr)
    return result


def setup_swebench_repo(
    repo_url: str,
    repo_dir: Path,
    base_commit: str,
    branch_name: str,
) -> tuple[bool, str]:
    """Clone repo and checkout base_commit for SWE-bench instance.

    This function ensures the repository is in the correct state for solving
    a SWE-bench instance:
    1. Clone the repository if it doesn't exist
    2. Fetch latest changes
    3. Checkout the specific base_commit
    4. Create a fresh fix branch

    Args:
        repo_url: GitHub repo URL (e.g., "https://github.com/django/django.git")
        repo_dir: Target directory for clone
        base_commit: Commit hash to checkout (from SWE-bench dataset)
        branch_name: Branch name to create for the fix

    Returns:
        (success, message) tuple
    """
    try:
        # Ensure parent directory exists
        repo_dir.parent.mkdir(parents=True, exist_ok=True)

        # Clone if not exists
        if not repo_dir.exists():
            result = _run_git(
                ["git", "clone", repo_url, str(repo_dir)],
                timeout=300,  # 5 min timeout for large repos
            )
            if result.returncode != 0:
                return False, f"Clone failed: {result.stderr}"

        # Reset any uncommitted changes
        _run_git(["git", "reset", "--hard"], cwd=repo_dir)

        # Clean untracked files
        _run_git(["git", "clean", "-fd"], cwd=repo_dir)

        # Fetch latest (in case base_commit is not in local history)
        _run_git(["git", "fetch", "origin"], cwd=repo_dir, timeout=180)

        # Checkout base_commit
        result = _run_git(["git", "checkout", base_commit], cwd=repo_dir)
        if result.returncode != 0:
            return False, f"Checkout failed: {result.stderr}"

        # Delete fix branch if it exists (for re-runs)
        _run_git(["git", "branch", "-D", branch_name], cwd=repo_dir)

        # Create fresh fix branch
        result = _run_git(["git", "checkout", "-b", branch_name], cwd=repo_dir)
        if result.returncode != 0:
            return False, f"Branch creation failed: {result.stderr}"

        return True, "Repository ready"

    except subprocess.TimeoutExpired:
        return False, "Git operation timed out"
    except Exception as e:
        return False, str(e)


def setup_github_repo(
    repo_url: str,
    repo_dir: Path,
    branch_name: str,
) -> tuple[bool, str]:
    """Clone repo for GitHub issue mode.

    Similar to setup_swebench_repo but doesn't checkout a specific commit.

    Args:
        repo_url: GitHub repo URL
        repo_dir: Target directory for clone
        branch_name: Branch name to create for the fix

    Returns:
        (success, message) tuple
    """
    try:
        repo_dir.parent.mkdir(parents=True, exist_ok=True)

        # Clone if not exists
        if not repo_dir.exists():
            result = _run_git(
                ["git", "clone", repo_url, str(repo_dir)],
                timeout=300,
            )
            if result.returncode != 0:
                return False, f"Clone failed: {result.stderr}"
        else:
            # Pull latest if repo exists
            _run_git(["git", "fetch", "origin"], cwd=repo_dir)
            _run_git(["git", "checkout", "main"], cwd=repo_dir)
            _run_git(["git", "pull", "origin", "main"], cwd=repo_dir)

        # Delete fix branch if it exists
        _run_git(["git", "branch", "-D", branch_name], cwd=repo_dir)

        # Create fix branch
        result = _run_git(["git", "checkout", "-b", branch_name], cwd=repo_dir)
        if result.returncode != 0:
            return False, f"Branch creation failed: {result.stderr}"

        return True, "Repository ready"

    except subprocess.TimeoutExpired:
        return False, "Git operation timed out"
    except Exception as e:
        return False, str(e)
