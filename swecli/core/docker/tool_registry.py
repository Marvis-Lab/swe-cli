"""Docker Tool Registry - Routes tool calls to Docker runtime.

This registry wraps the DockerToolHandler to provide a compatible interface
with the standard ToolRegistry, allowing tools to be executed inside Docker
while maintaining the same API for agents.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from .tool_handler import DockerToolHandler

__all__ = ["DockerToolRegistry"]

logger = logging.getLogger(__name__)


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
        docker_handler: "DockerToolHandler",
        local_registry: Any = None,
        path_mapping: dict[str, str] | None = None,
    ):
        """Initialize with a Docker tool handler and optional local fallback.

        Args:
            docker_handler: DockerToolHandler instance
            local_registry: Optional local ToolRegistry for fallback on unsupported tools
            path_mapping: Mapping of Docker paths to local paths for local-only tools
        """
        self.handler = docker_handler
        self._local_registry = local_registry
        self._path_mapping = path_mapping or {}
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
        # Track last run_command result for todo verification (Layer 1 & 2)
        self._last_run_command_result: dict[str, Any] | None = None

    def _remap_paths_to_local(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Remap Docker paths in arguments to local paths.

        Uses the path_mapping to convert Docker paths (e.g., /workspace/paper.pdf)
        back to their original local paths for local-only tool execution.

        Args:
            arguments: Tool arguments that may contain Docker paths

        Returns:
            Arguments with Docker paths replaced by local paths
        """
        if not self._path_mapping:
            return arguments

        remapped = dict(arguments)
        for key, value in remapped.items():
            if isinstance(value, str):
                # Check if this value matches a Docker path in our mapping
                for docker_path, local_path in self._path_mapping.items():
                    # Match exact Docker path or path ending with Docker path
                    if value == docker_path or value.endswith(docker_path):
                        remapped[key] = local_path
                        logger.info(f"  Remapped {key}: {value} → {local_path}")
                        break
                    # Also match by filename (for when LLM outputs just the filename)
                    docker_filename = Path(docker_path).name
                    if value == docker_filename or value.endswith(f"/{docker_filename}"):
                        remapped[key] = local_path
                        logger.info(f"  Remapped {key} (by filename): {value} → {local_path}")
                        break
        return remapped

    def _sanitize_local_paths(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Sanitize local paths in arguments to relative paths.

        This is a safety net that catches any local paths the LLM might output
        and converts them to just filenames for Docker execution.

        Args:
            arguments: Tool arguments that may contain local paths

        Returns:
            Arguments with local paths replaced by filenames
        """
        import re
        sanitized = dict(arguments)
        for key, value in sanitized.items():
            if isinstance(value, str):
                # Match absolute paths starting with /Users/, /home/, /var/, etc.
                match = re.match(r'^(/Users/|/home/|/var/|/tmp/).+/([^/]+)$', value)
                if match:
                    filename = match.group(2)
                    sanitized[key] = filename
                    logger.warning(f"Sanitized local path: {value} → {filename}")
        return sanitized

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
        # Sanitize any local paths in arguments (safety net for LLM outputs)
        arguments = self._sanitize_local_paths(arguments)

        # Logging to trace tool routing (INFO for visibility during testing)
        logger.info(f"DockerToolRegistry.execute_tool: {tool_name}")
        logger.debug(f"  sync_handlers: {list(self._sync_handlers.keys())}")
        logger.debug(f"  local_only_tools: {self._local_only_tools}")

        # Check if tool should run locally (not in Docker)
        if tool_name in self._local_only_tools:
            logger.info(f"  → Routing to LOCAL (local-only tool: {tool_name})")
            if self._local_registry is not None:
                # Remap Docker paths to local paths for local execution
                local_arguments = self._remap_paths_to_local(arguments)
                # Fall back to local registry for this tool
                return self._local_registry.execute_tool(
                    tool_name,
                    local_arguments,
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
            # LAYER 2: Block complete_todo if last run_command failed
            if tool_name == "complete_todo" and self._last_run_command_result:
                last = self._last_run_command_result
                exit_code = last.get("exit_code", 0)
                output = last.get("output", "")

                if self._check_command_has_error(exit_code, output):
                    # Truncate error output for readability
                    error_preview = output[:500] if output else "No output"
                    logger.warning(
                        f"  → Blocked complete_todo: last run_command failed (exit_code={exit_code})"
                    )
                    return {
                        "success": False,
                        "error": (
                            f"Cannot complete todo: last run_command failed.\n\n"
                            f"Exit code: {exit_code}\n"
                            f"Output:\n{error_preview}\n\n"
                            f"Fix the error and run the command successfully before completing this todo."
                        ),
                        "output": None,
                        "blocked_by": "command_verification",
                    }

                # Clear state after successful verification (command succeeded)
                logger.info("  → Cleared _last_run_command_result (command succeeded)")
                self._last_run_command_result = None

            # Try local fallback for unknown tools
            logger.info(f"  → Routing to LOCAL (unknown tool: {tool_name}, not in sync_handlers)")
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

        logger.info(f"  → Routing to DOCKER handler: {tool_name}")

        # For run_command, inject default working_dir if not specified
        # This ensures commands run from /workspace where files are written
        if tool_name == "run_command" and "working_dir" not in arguments:
            arguments = dict(arguments)
            arguments["working_dir"] = self.handler.workspace_dir
            logger.info(f"  → Injected default working_dir: {self.handler.workspace_dir}")

        handler = self._sync_handlers[tool_name]
        result = handler(arguments)

        # LAYER 1: Track run_command results and inject retry prompt on failure
        if tool_name == "run_command":
            self._last_run_command_result = result

            # Check for failure indicators
            exit_code = result.get("exit_code", 0)
            output = result.get("output", "")
            has_error = self._check_command_has_error(exit_code, output)

            if has_error:
                # Inject retry prompt to force LLM to fix before proceeding
                # Store in _llm_suffix so UI doesn't display it, only LLM sees it
                retry_prompt = (
                    "\n\n⚠️ COMMAND FAILED (exit code {})\n"
                    "You MUST fix this error before proceeding.\n"
                    "Do NOT call complete_todo until this command succeeds.\n"
                    "Steps:\n"
                    "1. Analyze the error above\n"
                    "2. Fix the issue (edit files, install deps, etc.)\n"
                    "3. Run the command again\n"
                    "4. Only proceed after success"
                ).format(exit_code)
                result = dict(result)
                result["_llm_suffix"] = retry_prompt  # Hidden from UI, visible to LLM
                logger.info("  → Injected retry prompt (command failed)")

        logger.info(f"  → Docker result: success={result.get('success')}")
        return result

    def _check_command_has_error(self, exit_code: int, output: str) -> bool:
        """Check if command output indicates an error.

        Args:
            exit_code: Command exit code
            output: Command output string

        Returns:
            True if the command appears to have failed
        """
        if exit_code != 0:
            return True

        # Check for common error patterns in output
        error_patterns = [
            "Error:",
            "error:",
            "ERROR:",
            "ModuleNotFoundError",
            "ImportError",
            "No such file or directory",
            "SyntaxError",
            "TypeError",
            "ValueError",
            "Traceback (most recent call last)",
            "FileNotFoundError",
            "NameError",
            "AttributeError",
        ]
        for pattern in error_patterns:
            if pattern in output:
                return True

        return False

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
