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

from .tool_registry import DockerToolRegistry
from .tools.file_ops import FileOperationsTool
from .tools.list_files import ListFilesTool
from .tools.run_command import RunCommandTool
from .tools.search import SearchTool

if TYPE_CHECKING:
    from .remote_runtime import RemoteRuntime

__all__ = ["DockerToolHandler", "DockerToolRegistry"]

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

        # Initialize tools
        self.run_command_tool = RunCommandTool(runtime, workspace_dir, shell_init)
        self.file_ops_tool = FileOperationsTool(runtime, workspace_dir)
        self.list_files_tool = ListFilesTool(runtime, workspace_dir)
        self.search_tool = SearchTool(runtime, workspace_dir)

    async def run_command(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Execute a command inside the Docker container."""
        return await self.run_command_tool.execute(arguments, context)

    async def read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Read a file from inside the Docker container."""
        return await self.file_ops_tool.read_file(arguments)

    async def write_file(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Write a file inside the Docker container."""
        return await self.file_ops_tool.write_file(arguments, context)

    async def edit_file(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Edit a file inside the Docker container using sed-like replacement."""
        return await self.file_ops_tool.edit_file(arguments, context)

    async def list_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """List files in a directory inside the Docker container."""
        return await self.list_files_tool.execute(arguments)

    async def search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Search for text in files inside the Docker container."""
        return await self.search_tool.execute(arguments)

    def _translate_path(self, path: str) -> str:
        """Translate a host path to a container path.

        Delegates to the file operations tool implementation for backward compatibility.
        """
        return self.file_ops_tool._translate_path(path)

    def _find_content(self, original: str, old_content: str) -> tuple[bool, str]:
        """Find content in file, with fallback to normalized matching.

        Delegates to the file operations tool implementation for backward compatibility.
        """
        return self.file_ops_tool._find_content(original, old_content)

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
