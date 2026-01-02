"""SubAgent manager for creating and executing subagents."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swecli.models.config import AppConfig

from .specs import CompiledSubAgent, SubAgentSpec


@dataclass
class SubAgentDeps:
    """Dependencies for subagent execution."""
    mode_manager: Any
    approval_manager: Any
    undo_manager: Any


class SubAgentManager:
    """Manages subagent creation and execution.

    SubAgents are ephemeral agents that handle isolated tasks.
    They receive a task description, execute with their own context,
    and return a single result.
    """

    def __init__(
        self,
        config: AppConfig,
        tool_registry: Any,
        mode_manager: Any,
        working_dir: Any = None,
    ) -> None:
        """Initialize the SubAgentManager.

        Args:
            config: Application configuration
            tool_registry: The tool registry for tool execution
            mode_manager: Mode manager for operation mode
            working_dir: Working directory for file operations
        """
        self._config = config
        self._tool_registry = tool_registry
        self._mode_manager = mode_manager
        self._working_dir = working_dir
        self._agents: dict[str, CompiledSubAgent] = {}
        self._all_tool_names: list[str] = self._get_all_tool_names()

    def _get_all_tool_names(self) -> list[str]:
        """Get list of all available tool names from registry.

        Note: Todo tools (write_todos, update_todo, etc.) are intentionally
        excluded. Only the main agent manages task tracking - subagents
        focus purely on execution.
        """
        return [
            "read_file",
            "write_file",
            "edit_file",
            "list_files",
            "search",
            "run_command",
            "list_processes",
            "get_process_output",
            "kill_process",
            "fetch_url",
            "analyze_image",
            "capture_screenshot",
            "list_screenshots",
            "capture_web_screenshot",
            "read_pdf",
        ]

    def register_subagent(self, spec: SubAgentSpec) -> None:
        """Register a subagent from specification.

        Args:
            spec: The subagent specification
        """
        from swecli.core.agents import SwecliAgent

        # Create a filtered tool registry if tools are specified
        tool_names = spec.get("tools", self._all_tool_names)

        # Create the subagent instance
        agent = SwecliAgent(
            config=self._get_subagent_config(spec),
            tool_registry=self._tool_registry,
            mode_manager=self._mode_manager,
            working_dir=self._working_dir,
        )

        # Override system prompt for subagent
        agent._subagent_system_prompt = spec["system_prompt"]

        self._agents[spec["name"]] = CompiledSubAgent(
            name=spec["name"],
            description=spec["description"],
            agent=agent,
            tool_names=tool_names,
        )

    def _get_subagent_config(self, spec: SubAgentSpec) -> AppConfig:
        """Create config for subagent, potentially with model override."""
        if "model" in spec and spec["model"]:
            # Create a copy with model override
            return AppConfig(
                model=spec["model"],
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                api_key=self._config.api_key,
                api_base_url=self._config.api_base_url,
            )
        return self._config

    def register_defaults(self) -> None:
        """Register all default subagents."""
        from .agents import ALL_SUBAGENTS

        for spec in ALL_SUBAGENTS:
            self.register_subagent(spec)

    def get_subagent(self, name: str) -> CompiledSubAgent | None:
        """Get a registered subagent by name.

        Args:
            name: The subagent name

        Returns:
            The compiled subagent or None if not found
        """
        return self._agents.get(name)

    def get_available_types(self) -> list[str]:
        """Get list of available subagent type names.

        Returns:
            List of registered subagent names
        """
        return list(self._agents.keys())

    def get_descriptions(self) -> dict[str, str]:
        """Get descriptions for all registered subagents.

        Returns:
            Dict mapping subagent name to description
        """
        return {name: agent["description"] for name, agent in self._agents.items()}

    def _is_docker_available(self) -> bool:
        """Check if Docker is available on the system."""
        return shutil.which("docker") is not None

    def _get_spec_for_subagent(self, name: str) -> SubAgentSpec | None:
        """Get the SubAgentSpec for a registered subagent."""
        from .agents import ALL_SUBAGENTS
        return next((s for s in ALL_SUBAGENTS if s["name"] == name), None)

    def _extract_input_files(self, task: str, local_working_dir: Path) -> list[Path]:
        """Extract file paths referenced in the task.

        Looks for:
        - @filename patterns (e.g., @2303.11366v4.pdf)
        - Quoted file paths
        - Absolute paths that exist

        Args:
            task: The task description string
            local_working_dir: Local working directory to resolve relative paths

        Returns:
            List of existing file paths to copy into Docker
        """
        import re
        files: list[Path] = []
        seen: set[str] = set()

        # Pattern 1: @filename (common for PDF/file references)
        at_mentions = re.findall(r'@([\w\-\.]+\.[a-zA-Z0-9]+)', task)
        for filename in at_mentions:
            if filename in seen:
                continue
            path = local_working_dir / filename
            if path.exists() and path.is_file():
                files.append(path)
                seen.add(filename)

        # Pattern 2: Quoted file paths with common extensions
        quoted_paths = re.findall(
            r'["\']([^"\']+\.(?:pdf|png|jpg|jpeg|svg|csv|json|yaml|yml))["\']',
            task,
            re.I
        )
        for p in quoted_paths:
            if p in seen:
                continue
            path = Path(p) if Path(p).is_absolute() else local_working_dir / p
            if path.exists() and path.is_file():
                files.append(path)
                seen.add(p)

        return files

    def _copy_files_to_docker(
        self,
        docker_handler: Any,
        files: list[Path],
        workspace_dir: str,
        ui_callback: Any = None,
    ) -> None:
        """Copy local files into Docker container.

        Args:
            docker_handler: DockerToolHandler for executing commands
            files: List of local file paths to copy
            workspace_dir: Target directory in Docker container
            ui_callback: Optional UI callback for progress display
        """
        import base64

        for local_file in files:
            # Show copy progress
            if ui_callback and hasattr(ui_callback, 'on_tool_call'):
                ui_callback.on_tool_call("docker_copy", {"file": local_file.name})

            try:
                # Read file content locally
                content = local_file.read_bytes()

                # For binary files, use base64 encoding
                encoded = base64.b64encode(content).decode('ascii')

                # Write to Docker via base64 decode
                docker_path = f"{workspace_dir}/{local_file.name}"

                # Use printf for large content to avoid shell argument limits
                # Split into chunks if needed
                chunk_size = 50000  # Safe size for shell
                if len(encoded) > chunk_size:
                    # Write in chunks
                    docker_handler.run_command_sync({
                        "command": f"rm -f {docker_path}"
                    })
                    for i in range(0, len(encoded), chunk_size):
                        chunk = encoded[i:i + chunk_size]
                        docker_handler.run_command_sync({
                            "command": f"printf '%s' '{chunk}' >> {docker_path}.b64"
                        })
                    docker_handler.run_command_sync({
                        "command": f"base64 -d {docker_path}.b64 > {docker_path} && rm {docker_path}.b64"
                    })
                else:
                    docker_handler.run_command_sync({
                        "command": f"printf '%s' '{encoded}' | base64 -d > {docker_path}"
                    })

                # Show completion
                if ui_callback and hasattr(ui_callback, 'on_tool_result'):
                    ui_callback.on_tool_result("docker_copy", {"file": local_file.name}, {
                        "success": True,
                        "output": f"Copied to {docker_path}",
                    })

            except Exception as e:
                if ui_callback and hasattr(ui_callback, 'on_tool_result'):
                    ui_callback.on_tool_result("docker_copy", {"file": local_file.name}, {
                        "success": False,
                        "error": str(e),
                    })

    def _rewrite_task_for_docker(
        self,
        task: str,
        input_files: list[Path],
        workspace_dir: str,
    ) -> str:
        """Rewrite task to reference Docker paths instead of local paths.

        Args:
            task: Original task description
            input_files: List of files that were copied to Docker
            workspace_dir: Docker workspace directory

        Returns:
            Task with paths rewritten to Docker paths
        """
        new_task = task
        for local_file in input_files:
            docker_path = f"{workspace_dir}/{local_file.name}"
            # Replace @filename with Docker path
            new_task = new_task.replace(f"@{local_file.name}", docker_path)
            # Also replace any absolute local paths
            new_task = new_task.replace(str(local_file), docker_path)
        return new_task

    def _execute_with_docker(
        self,
        name: str,
        task: str,
        deps: SubAgentDeps,
        spec: SubAgentSpec,
        ui_callback: Any = None,
        task_monitor: Any = None,
    ) -> dict[str, Any]:
        """Execute a subagent inside Docker with automatic container lifecycle.

        This method:
        1. Starts a Docker container with the spec's docker_config
        2. Executes the subagent with all tools routed through Docker
        3. Copies generated files from container to local working directory
        4. Stops the container

        Args:
            name: The subagent type name
            task: The task description
            deps: Dependencies for tool execution
            spec: The subagent specification with docker_config
            ui_callback: Optional UI callback
            task_monitor: Optional task monitor

        Returns:
            Result dict with content, success, and messages
        """
        import asyncio
        from swecli.core.docker.deployment import DockerDeployment
        from swecli.core.docker.tool_handler import DockerToolHandler

        docker_config = spec.get("docker_config")
        if docker_config is None:
            return {
                "success": False,
                "error": "No docker_config in subagent spec",
                "content": "",
            }

        # Workspace inside Docker container
        workspace_dir = "/workspace"
        local_working_dir = Path(self._working_dir) if self._working_dir else Path.cwd()

        deployment = None
        loop = None
        try:
            # Show Docker start as a tool call with spinner
            if ui_callback and hasattr(ui_callback, 'on_tool_call'):
                ui_callback.on_tool_call("docker_start", {"image": docker_config.image})

            # Create and start Docker deployment
            deployment = DockerDeployment(config=docker_config)

            # Run async start in sync context - use a single event loop for the whole operation
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(deployment.start())

            # Show Docker start completion
            if ui_callback and hasattr(ui_callback, 'on_tool_result'):
                ui_callback.on_tool_result("docker_start", {"image": docker_config.image}, {
                    "success": True,
                    "output": docker_config.image,
                })

            # Create Docker tool handler with local registry fallback for tools like read_pdf
            runtime = deployment.runtime
            shell_init = docker_config.shell_init if hasattr(docker_config, 'shell_init') else ""
            docker_handler = DockerToolHandler(
                runtime,
                workspace_dir=workspace_dir,
                shell_init=shell_init,
            )

            # Extract input files from task (PDFs, images, etc.)
            input_files = self._extract_input_files(task, local_working_dir)

            # Copy input files into Docker container
            if input_files:
                self._copy_files_to_docker(docker_handler, input_files, workspace_dir, ui_callback)

            # Rewrite task to use Docker paths
            docker_task = self._rewrite_task_for_docker(task, input_files, workspace_dir)

            # Execute subagent with Docker tools (local_registry passed for fallback)
            result = self.execute_subagent(
                name=name,
                task=docker_task,  # Use rewritten task with Docker paths
                deps=deps,
                ui_callback=ui_callback,
                task_monitor=task_monitor,
                working_dir=workspace_dir,
                docker_handler=docker_handler,
            )

            # Copy generated files from Docker to local working directory
            if result.get("success"):
                self._copy_files_from_docker(
                    docker_handler=docker_handler,
                    workspace_dir=workspace_dir,
                    local_dir=local_working_dir,
                )

            return result

        except Exception as e:
            import traceback
            return {
                "success": False,
                "error": f"Docker execution failed: {str(e)}\n{traceback.format_exc()}",
                "content": "",
            }
        finally:
            # Always stop the container
            if deployment is not None and loop is not None:
                try:
                    loop.run_until_complete(deployment.stop())
                except Exception:
                    pass  # Ignore cleanup errors
            # Close the loop after all async operations
            if loop is not None:
                try:
                    loop.close()
                except Exception:
                    pass

    def _copy_files_from_docker(
        self,
        docker_handler: Any,
        workspace_dir: str,
        local_dir: Path,
    ) -> None:
        """Copy generated files from Docker container to local directory.

        Copies common code files: .py, .yaml, .toml, .txt, .json, .md
        """
        try:
            # List files in workspace
            result = docker_handler.list_files_sync({"path": workspace_dir})
            if not result.get("success"):
                return

            files = result.get("output", "").strip().split("\n")

            # File extensions to copy
            copy_extensions = {".py", ".yaml", ".yml", ".toml", ".txt", ".json", ".md", ".cfg"}

            for file_entry in files:
                file_entry = file_entry.strip()
                if not file_entry:
                    continue

                # Extract filename from listing (handle various formats)
                filename = file_entry.split()[-1] if file_entry else ""
                if not filename or filename.startswith("."):
                    continue

                # Check extension
                file_path = Path(filename)
                if file_path.suffix.lower() not in copy_extensions:
                    continue

                # Read file from Docker
                docker_path = f"{workspace_dir}/{filename}"
                read_result = docker_handler.read_file_sync({"file_path": docker_path})
                if not read_result.get("success"):
                    continue

                content = read_result.get("output", "")

                # Write to local directory
                local_path = local_dir / filename
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_text(content)

        except Exception:
            pass  # Ignore copy errors, files may not exist

    def execute_subagent(
        self,
        name: str,
        task: str,
        deps: SubAgentDeps,
        ui_callback: Any = None,
        task_monitor: Any = None,
        working_dir: Any = None,
        docker_handler: Any = None,
    ) -> dict[str, Any]:
        """Execute a subagent synchronously with the given task.

        Args:
            name: The subagent type name
            task: The task description for the subagent
            deps: Dependencies for tool execution
            ui_callback: Optional UI callback for displaying tool calls
            task_monitor: Optional task monitor for interrupt support
            working_dir: Optional working directory override for the subagent
            docker_handler: Optional DockerToolHandler for Docker-based execution.
                           When provided, all tool calls are routed through Docker
                           instead of local execution.

        Returns:
            Result dict with content, success, and messages
        """
        # Auto-detect Docker execution for subagents with docker_config
        # Only trigger if docker_handler is not already provided (to avoid recursion)
        if docker_handler is None:
            spec = self._get_spec_for_subagent(name)
            if spec is not None and spec.get("docker_config") is not None:
                if self._is_docker_available():
                    # Execute with Docker lifecycle management
                    return self._execute_with_docker(
                        name=name,
                        task=task,
                        deps=deps,
                        spec=spec,
                        ui_callback=ui_callback,
                        task_monitor=task_monitor,
                    )
                # If Docker not available, fall through to local execution

        if name not in self._agents:
            available = ", ".join(self._agents.keys())
            return {
                "success": False,
                "error": f"Unknown subagent type '{name}'. Available: {available}",
                "content": "",
            }

        compiled = self._agents[name]

        # Determine which tool registry to use
        if docker_handler is not None:
            # Use Docker-based tool registry for Docker execution
            # Pass local registry for fallback on tools not supported in Docker (e.g., read_pdf)
            from swecli.core.docker.tool_handler import DockerToolRegistry
            tool_registry = DockerToolRegistry(docker_handler, local_registry=self._tool_registry)
        else:
            tool_registry = self._tool_registry

        # If working_dir or docker_handler is provided, create a new agent
        # Otherwise use the pre-registered agent
        if working_dir is not None or docker_handler is not None:
            from swecli.core.agents import SwecliAgent
            from .agents import ALL_SUBAGENTS

            # Find the spec for this subagent
            spec = next((s for s in ALL_SUBAGENTS if s["name"] == name), None)
            if spec is None:
                return {
                    "success": False,
                    "error": f"Spec not found for subagent '{name}'",
                    "content": "",
                }

            # Create new agent with overridden tool_registry and/or working_dir
            agent = SwecliAgent(
                config=self._get_subagent_config(spec),
                tool_registry=tool_registry,
                mode_manager=self._mode_manager,
                working_dir=working_dir if working_dir is not None else self._working_dir,
            )
            # Apply system prompt override
            if spec.get("system_prompt"):
                agent.system_prompt = spec["system_prompt"]
        else:
            agent = compiled["agent"]

        # Create nested callback wrapper if parent callback provided
        nested_callback = None
        if ui_callback is not None:
            from swecli.ui_textual.nested_callback import NestedUICallback
            nested_callback = NestedUICallback(
                parent_callback=ui_callback,
                parent_context=name,
                depth=1,
            )

        # Execute with isolated context (fresh message history)
        # max_iterations=None allows unlimited iterations - subagent runs until natural completion
        result = agent.run_sync(
            message=task,
            deps=deps,
            message_history=None,  # Fresh context for subagent
            ui_callback=nested_callback,
            max_iterations=None,  # Unlimited - run until natural completion
            task_monitor=task_monitor,  # Pass task monitor for interrupt support
        )

        return result

    async def execute_subagent_async(
        self,
        name: str,
        task: str,
        deps: SubAgentDeps,
        ui_callback: Any = None,
    ) -> dict[str, Any]:
        """Execute a subagent asynchronously.

        Uses asyncio.to_thread to run the synchronous agent in a thread pool.

        Args:
            name: The subagent type name
            task: The task description for the subagent
            deps: Dependencies for tool execution
            ui_callback: Optional UI callback for displaying tool calls

        Returns:
            Result dict with content, success, and messages
        """
        return await asyncio.to_thread(
            self.execute_subagent, name, task, deps, ui_callback
        )

    async def execute_parallel(
        self,
        tasks: list[tuple[str, str]],
        deps: SubAgentDeps,
        ui_callback: Any = None,
    ) -> list[dict[str, Any]]:
        """Execute multiple subagents in parallel.

        Args:
            tasks: List of (subagent_name, task_description) tuples
            deps: Dependencies for tool execution
            ui_callback: Optional UI callback for displaying tool calls

        Returns:
            List of results from each subagent
        """
        coroutines = [
            self.execute_subagent_async(name, task, deps, ui_callback)
            for name, task in tasks
        ]
        return await asyncio.gather(*coroutines)
