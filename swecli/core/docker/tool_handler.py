"""DockerToolHandler - Routes tool calls to Docker runtime.

This handler executes tools inside the Docker container instead of locally.
It translates swecli tool calls into RemoteRuntime operations.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from .remote_runtime import RemoteRuntime

__all__ = ["DockerToolHandler", "DockerToolRegistry"]

logger = logging.getLogger(__name__)


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

        if not path:
            return {
                "success": False,
                "error": "file_path or path is required",
                "output": None,
            }

        # Translate path to container path
        container_path = self._translate_path(path)

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

            # Check if old_text exists
            if old_text not in content:
                return {
                    "success": False,
                    "error": f"old_text not found in {container_path}",
                    "output": None,
                }

            # Perform replacement
            new_content = content.replace(old_text, new_text, 1)

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

            return {
                "success": obs.exit_code == 0,
                "output": obs.output,
                "error": obs.failure_reason if obs.exit_code != 0 else None,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
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

        # If it's an absolute host path, extract the repo-relative part
        # e.g., /Users/foo/bar/repo/src/file.py -> /workspace/src/file.py
        try:
            p = Path(path)
            if p.is_absolute():
                # Try to find a common repo pattern and extract relative path
                parts = p.parts
                # Look for common patterns that indicate repo root
                for i, part in enumerate(parts):
                    if part in {"src", "lib", "tests", "test", "docs"} or part.endswith(".git"):
                        # Take from one level up
                        if i > 0:
                            relative = "/".join(parts[i:])
                            return f"{self.workspace_dir}/{relative}"

                # Default: just use the filename/last few parts
                if len(parts) > 2:
                    relative = "/".join(parts[-2:])
                    return f"{self.workspace_dir}/{relative}"
                return f"{self.workspace_dir}/{p.name}"
        except Exception:
            pass

        # Assume it's relative to workspace
        return f"{self.workspace_dir}/{path}"

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
        return asyncio.run(fresh.run_command(arguments, context))

    def read_file_sync(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Synchronous wrapper for read_file."""
        fresh = self._create_fresh_handler()
        return asyncio.run(fresh.read_file(arguments))

    def write_file_sync(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Synchronous wrapper for write_file."""
        fresh = self._create_fresh_handler()
        return asyncio.run(fresh.write_file(arguments, context))

    def edit_file_sync(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Synchronous wrapper for edit_file."""
        fresh = self._create_fresh_handler()
        return asyncio.run(fresh.edit_file(arguments, context))

    def list_files_sync(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Synchronous wrapper for list_files."""
        fresh = self._create_fresh_handler()
        return asyncio.run(fresh.list_files(arguments))

    def search_sync(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Synchronous wrapper for search."""
        fresh = self._create_fresh_handler()
        return asyncio.run(fresh.search(arguments))


class DockerToolRegistry:
    """A tool registry that routes tools through Docker.

    This wraps the Docker tool handler to provide a compatible interface
    with the standard ToolRegistry. Uses synchronous wrappers for compatibility
    with SwecliAgent.

    For tools not supported in Docker (like read_pdf), falls back to the
    local tool registry if provided.
    """

    def __init__(
        self,
        docker_handler: DockerToolHandler,
        local_registry: Any = None,
    ):
        """Initialize with a Docker tool handler and optional local fallback.

        Args:
            docker_handler: DockerToolHandler instance
            local_registry: Optional local ToolRegistry for fallback on unsupported tools
        """
        self.handler = docker_handler
        self._local_registry = local_registry
        # Use sync handlers for compatibility with SwecliAgent
        self._sync_handlers = {
            "run_command": self.handler.run_command_sync,
            "read_file": self.handler.read_file_sync,
            "write_file": self.handler.write_file_sync,
            "edit_file": self.handler.edit_file_sync,
            "list_files": self.handler.list_files_sync,
            "search": self.handler.search_sync,
        }
        # Tools that should always run locally (not in Docker)
        self._local_only_tools = {"read_pdf", "analyze_image", "capture_screenshot"}

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        mode_manager: Union[Any, None] = None,
        approval_manager: Union[Any, None] = None,
        undo_manager: Union[Any, None] = None,
        task_monitor: Union[Any, None] = None,
        session_manager: Union[Any, None] = None,
        ui_callback: Union[Any, None] = None,
        is_subagent: bool = False,
    ) -> dict[str, Any]:
        """Execute a tool synchronously via Docker.

        This method matches the ToolRegistry.execute_tool interface so it can
        be used as a drop-in replacement when running in Docker mode.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            mode_manager: Mode manager (unused in Docker)
            approval_manager: Approval manager (unused in Docker)
            undo_manager: Undo manager (unused in Docker)
            task_monitor: Task monitor (unused in Docker)
            session_manager: Session manager (unused in Docker)
            ui_callback: UI callback (unused in Docker)
            is_subagent: Whether running as subagent (unused in Docker)

        Returns:
            Tool execution result
        """
        # Check if tool should run locally (not in Docker)
        if tool_name in self._local_only_tools:
            if self._local_registry is not None:
                # Fall back to local registry for this tool
                return self._local_registry.execute_tool(
                    tool_name,
                    arguments,
                    mode_manager=mode_manager,
                    approval_manager=approval_manager,
                    undo_manager=undo_manager,
                    task_monitor=task_monitor,
                    session_manager=session_manager,
                    ui_callback=ui_callback,
                    is_subagent=is_subagent,
                )
            else:
                return {
                    "success": False,
                    "error": f"Tool '{tool_name}' requires local execution but no local registry available",
                    "output": None,
                }

        if tool_name not in self._sync_handlers:
            # Try local fallback for unknown tools
            if self._local_registry is not None:
                return self._local_registry.execute_tool(
                    tool_name,
                    arguments,
                    mode_manager=mode_manager,
                    approval_manager=approval_manager,
                    undo_manager=undo_manager,
                    task_monitor=task_monitor,
                    session_manager=session_manager,
                    ui_callback=ui_callback,
                    is_subagent=is_subagent,
                )
            return {
                "success": False,
                "error": f"Tool '{tool_name}' not supported in Docker mode",
                "output": None,
            }

        handler = self._sync_handlers[tool_name]
        return handler(arguments)

    def get_tool_specs(self) -> list[dict[str, Any]]:
        """Return tool specifications for the agent.

        Returns the same tool specs as the standard registry so the agent
        knows what tools are available.
        """
        return [
            {
                "name": "run_command",
                "description": "Execute a shell command in the Docker container",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The command to execute",
                        },
                        "timeout": {
                            "type": "number",
                            "description": "Timeout in seconds (default: 120)",
                        },
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "read_file",
                "description": "Read a file from the Docker container",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file (relative to /workspace/repo)",
                        },
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write content to a file in the Docker container",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file",
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "edit_file",
                "description": "Edit a file by replacing text in the Docker container",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "Text to find and replace",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text",
                        },
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
            {
                "name": "list_files",
                "description": "List files in a directory in the Docker container",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Directory path",
                        },
                        "pattern": {
                            "type": "string",
                            "description": "File pattern to match",
                        },
                        "recursive": {
                            "type": "boolean",
                            "description": "Search recursively",
                        },
                    },
                },
            },
            {
                "name": "search",
                "description": "Search for text in files in the Docker container",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "path": {
                            "type": "string",
                            "description": "Path to search in",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["text", "ast"],
                            "description": "Search type",
                        },
                    },
                    "required": ["query"],
                },
            },
        ]

    async def execute_tool_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: Any = None,
    ) -> dict[str, Any]:
        """Execute a tool asynchronously via Docker.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            context: Execution context

        Returns:
            Tool execution result
        """
        # Map to async handlers
        async_handlers = {
            "run_command": self.handler.run_command,
            "read_file": self.handler.read_file,
            "write_file": self.handler.write_file,
            "edit_file": self.handler.edit_file,
            "list_files": self.handler.list_files,
            "search": self.handler.search,
        }

        if tool_name not in async_handlers:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' not supported in Docker mode",
                "output": None,
            }

        handler = async_handlers[tool_name]

        # Check if handler accepts context
        if tool_name in {"run_command", "write_file", "edit_file"}:
            return await handler(arguments, context)
        return await handler(arguments)
