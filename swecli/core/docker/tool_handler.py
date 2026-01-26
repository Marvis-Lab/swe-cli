"""DockerToolHandler - Routes tool calls to Docker runtime.

This handler executes tools inside the Docker container instead of locally.
It translates swecli tool calls into RemoteRuntime operations.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, Coroutine, TypeVar, Union

if TYPE_CHECKING:
    from .remote_runtime import RemoteRuntime

__all__ = ["DockerToolHandler"]

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine, handling both nested and standalone event loops.

    When called from within a running event loop (e.g., Textual UI), we can't use
    asyncio.run() directly. This helper detects that case and runs the coroutine
    in a separate thread with its own event loop.

    Args:
        coro: The coroutine to execute

    Returns:
        The result of the coroutine
    """
    try:
        # Check if there's already a running event loop
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - we can use asyncio.run() safely
        return asyncio.run(coro)

    # There's a running loop - run in a separate thread
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


class DockerToolHandler:
    """Execute tools via Docker runtime instead of local subprocess.

    This handler wraps a RemoteRuntime and provides methods that match
    the swecli tool interface, translating calls to HTTP operations.
    """

    def __init__(
        self,
        runtime: "RemoteRuntime",
        workspace_dir: str = "/testbed",
        shell_init: str = "",
    ):
        """Initialize the Docker tool handler.

        Args:
            runtime: RemoteRuntime instance for communicating with container
            workspace_dir: Directory inside container where repo is located
                          (default: /testbed for SWE-bench images)
            shell_init: Shell initialization command to prepend to all commands
                       (e.g., conda activation for SWE-bench, empty for uv images)
        """
        self.runtime = runtime
        self.workspace_dir = workspace_dir
        self.shell_init = shell_init

    async def run_command(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Execute a command inside the Docker container.

        Args:
            arguments: Tool arguments with 'command', 'timeout', 'working_dir'
            context: Tool execution context (unused in Docker mode)

        Returns:
            Result dict with success, output, exit_code
        """
        from .models import BashAction

        command = arguments.get("command", "")
        timeout = arguments.get("timeout", 120.0)
        working_dir = arguments.get("working_dir")

        if not command:
            return {
                "success": False,
                "error": "command is required",
                "output": None,
            }

        # Prepend cd if working_dir specified
        if working_dir:
            # Translate host path to container path if needed
            container_path = self._translate_path(working_dir)
            command = f"cd {container_path} && {command}"

        # Prepend shell initialization if configured
        # (e.g., conda activation for SWE-bench, empty for uv/plain images)
        if self.shell_init:
            command = f"{self.shell_init} && {command}"

        try:
            action = BashAction(
                command=command,
                timeout=timeout,
                check="silent",  # Don't raise on non-zero exit
            )
            obs = await self.runtime.run_in_session(action)

            return {
                "success": obs.exit_code == 0 or obs.exit_code is None,
                "output": obs.output,
                "exit_code": obs.exit_code,
                "error": obs.failure_reason if obs.exit_code != 0 else None,
            }
        except Exception as e:
            logger.error(f"Docker run_command failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "output": None,
            }

    async def read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Read a file from inside the Docker container.

        Args:
            arguments: Tool arguments with 'path'

        Returns:
            Result dict with success, content
        """
        # Accept both "file_path" (standard) and "path" (legacy) argument names
        path = arguments.get("file_path") or arguments.get("path", "")
        if not path:
            return {
                "success": False,
                "error": "file_path or path is required",
                "output": None,
            }

        # Translate path to container path
        container_path = self._translate_path(path)

        try:
            content = await self.runtime.read_file(container_path)
            return {
                "success": True,
                "output": content,
                "content": content,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "output": None,
            }

    async def write_file(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Write a file inside the Docker container.

        Args:
            arguments: Tool arguments with 'path', 'content'
            context: Tool execution context (unused in Docker mode)

        Returns:
            Result dict with success status
        """
        # Accept both "file_path" (standard) and "path" (legacy) argument names
        path = arguments.get("file_path") or arguments.get("path", "")
        content = arguments.get("content", "")

        # Debug: Confirm Docker write is being used
        logger.info(f"DockerToolHandler.write_file called with path: {path}")

        if not path:
            return {
                "success": False,
                "error": "file_path or path is required",
                "output": None,
            }

        # Translate path to container path
        container_path = self._translate_path(path)
        logger.info(f"  → Translated to Docker path: {container_path}")

        try:
            await self.runtime.write_file(container_path, content)
            return {
                "success": True,
                "output": f"Wrote {len(content)} bytes to {container_path}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "output": None,
            }

    async def edit_file(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Edit a file inside the Docker container using sed-like replacement.

        Args:
            arguments: Tool arguments with 'path', 'old_text', 'new_text'
            context: Tool execution context (unused in Docker mode)

        Returns:
            Result dict with success status, diff, lines_added, lines_removed
        """
        # Accept both standard and legacy argument names
        path = arguments.get("file_path") or arguments.get("path", "")
        old_text = arguments.get("old_content") or arguments.get("old_text", "")
        new_text = arguments.get("new_content") or arguments.get("new_text", "")

        if not path:
            return {
                "success": False,
                "error": "file_path or path is required",
                "output": None,
            }

        if not old_text:
            return {
                "success": False,
                "error": "old_content or old_text is required for editing",
                "output": None,
            }

        container_path = self._translate_path(path)

        try:
            # Read current content
            content = await self.runtime.read_file(container_path)

            # Check if old_text exists (with fuzzy matching fallback)
            found, actual_old_text = self._find_content(content, old_text)
            if not found:
                return {
                    "success": False,
                    "error": f"old_text not found in {container_path}",
                    "output": None,
                }

            # Perform replacement using actual matched content
            new_content = content.replace(actual_old_text, new_text, 1)

            # Calculate diff statistics before writing
            from swecli.core.context_engineering.tools.implementations.diff_preview import Diff
            diff = Diff(container_path, content, new_content)
            stats = diff.get_stats()
            diff_text = diff.generate_unified_diff(context_lines=3)

            # Write back
            await self.runtime.write_file(container_path, new_content)

            return {
                "success": True,
                "output": f"Edited {container_path}",
                "file_path": container_path,
                "lines_added": stats["lines_added"],
                "lines_removed": stats["lines_removed"],
                "diff": diff_text,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "output": None,
            }

    async def list_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """List files in a directory inside the Docker container.

        Args:
            arguments: Tool arguments with 'path', 'pattern', 'recursive'

        Returns:
            Result dict with file listing
        """
        # Accept multiple naming conventions for directory path
        path = (
            arguments.get("directory")
            or arguments.get("dir_path")
            or arguments.get("path", ".")
        )
        pattern = arguments.get("pattern", "*")
        recursive = arguments.get("recursive", False)

        container_path = self._translate_path(path)

        try:
            if recursive:
                cmd = f"find {container_path} -name '{pattern}' -type f 2>/dev/null | head -100"
            else:
                cmd = f"ls -la {container_path} 2>/dev/null"

            obs = await self.runtime.run(cmd, timeout=30.0)

            if obs.exit_code != 0:
                # Provide informative error message
                error_msg = obs.failure_reason or obs.output or f"Directory not found: {container_path}"
                return {
                    "success": False,
                    "output": None,
                    "error": error_msg,
                }

            return {
                "success": True,
                "output": obs.output or "(empty directory)",
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to list files in {container_path}: {str(e)}",
                "output": None,
            }

    async def search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Search for text in files inside the Docker container.

        Args:
            arguments: Tool arguments with 'query', 'path', 'type'

        Returns:
            Result dict with search results
        """
        # Accept both "pattern" (standard) and "query" (legacy) argument names
        query = arguments.get("pattern") or arguments.get("query", "")
        path = arguments.get("file_path") or arguments.get("path", ".")
        search_type = arguments.get("type", "text")

        if not query:
            return {
                "success": False,
                "error": "pattern or query is required for search",
                "output": None,
            }

        container_path = self._translate_path(path)

        try:
            if search_type == "text":
                # Use grep for text search
                cmd = f"grep -rn --include='*.py' --include='*.js' --include='*.ts' '{query}' {container_path} 2>/dev/null | head -50"
            else:
                # For AST search, fall back to grep (ast-grep may not be in container)
                cmd = f"grep -rn '{query}' {container_path} 2>/dev/null | head -50"

            obs = await self.runtime.run(cmd, timeout=60.0)

            return {
                "success": True,  # grep returns 1 if no matches, but that's OK
                "output": obs.output or "No matches found",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "output": None,
            }

    def _translate_path(self, path: str) -> str:
        """Translate a host path to a container path.

        If the path is already absolute and starts with /workspace, use as-is.
        Otherwise, assume it's relative to the workspace.

        Args:
            path: Host path or relative path

        Returns:
            Container path
        """
        if not path:
            return self.workspace_dir

        # If it's already a container path, use as-is
        if path.startswith("/testbed") or path.startswith("/workspace"):
            return path

        # Relative path - prepend workspace (strip leading ./)
        if not path.startswith("/"):
            clean_path = path.lstrip("./")
            return f"{self.workspace_dir}/{clean_path}"

        # Absolute host path (e.g., /Users/.../file.py)
        # Extract just the filename - safest for Docker since we can't know
        # the original repo structure
        try:
            p = Path(path)
            return f"{self.workspace_dir}/{p.name}"
        except Exception:
            pass

        # Fallback: just use the path as-is under workspace
        return f"{self.workspace_dir}/{path}"

    def _find_content(self, original: str, old_content: str) -> tuple[bool, str]:
        """Find content in file, with fallback to normalized matching.

        When exact match fails, tries to find content by normalizing whitespace
        (stripping each line, normalizing line endings) and then locating the
        actual content in the original file.

        Args:
            original: The original file content
            old_content: The content to find

        Returns:
            (found, actual_content) - actual_content is what should be replaced
        """
        # Try exact match first (fast path)
        if old_content in original:
            return (True, old_content)

        # Normalize: strip each line, normalize line endings
        def normalize(s: str) -> str:
            lines = s.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            return "\n".join(line.strip() for line in lines)

        norm_old = normalize(old_content)
        norm_original = normalize(original)

        # If normalized content not found, give up
        if norm_old not in norm_original:
            return (False, old_content)

        # Find actual content in original by line matching
        old_lines = [ln.strip() for ln in old_content.split("\n") if ln.strip()]
        if not old_lines:
            return (False, old_content)

        original_lines = original.split("\n")

        # Find start line that matches first stripped line
        for i, line in enumerate(original_lines):
            if line.strip() == old_lines[0]:
                # Try to match all subsequent lines
                matched_lines = []
                j = 0  # Index into old_lines
                for k in range(i, min(i + len(old_lines) * 2, len(original_lines))):
                    if j >= len(old_lines):
                        break
                    if original_lines[k].strip() == old_lines[j]:
                        matched_lines.append(original_lines[k])
                        j += 1

                if j == len(old_lines):
                    # Found all lines - reconstruct actual content
                    actual = "\n".join(matched_lines)
                    # Check if we need trailing newline
                    if actual in original:
                        return (True, actual)
                    if actual + "\n" in original:
                        return (True, actual + "\n")

        return (False, old_content)

    # Synchronous wrappers for use with SwecliAgent (which expects sync handlers)

    def _create_fresh_handler(self) -> "DockerToolHandler":
        """Create a fresh handler with a new runtime for thread-safe execution."""
        from .remote_runtime import RemoteRuntime

        fresh_runtime = RemoteRuntime(
            host=self.runtime.host,
            port=self.runtime.port,
            auth_token=self.runtime.auth_token,
            timeout=self.runtime.timeout,
        )
        return DockerToolHandler(fresh_runtime, self.workspace_dir, self.shell_init)

    def run_command_sync(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Synchronous wrapper for run_command.

        Always creates a fresh handler to avoid event loop issues with cached
        HTTP sessions. Each call gets a fresh RemoteRuntime/aiohttp session.
        """
        fresh = self._create_fresh_handler()
        return _run_async(fresh.run_command(arguments, context))

    def read_file_sync(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Synchronous wrapper for read_file."""
        fresh = self._create_fresh_handler()
        return _run_async(fresh.read_file(arguments))

    def write_file_sync(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Synchronous wrapper for write_file."""
        fresh = self._create_fresh_handler()
        return _run_async(fresh.write_file(arguments, context))

    def edit_file_sync(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Synchronous wrapper for edit_file."""
        fresh = self._create_fresh_handler()
        return _run_async(fresh.edit_file(arguments, context))

    def list_files_sync(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Synchronous wrapper for list_files."""
        fresh = self._create_fresh_handler()
        return _run_async(fresh.list_files(arguments))

    def search_sync(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Synchronous wrapper for search."""
        fresh = self._create_fresh_handler()
        return _run_async(fresh.search(arguments))
