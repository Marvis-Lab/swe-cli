"""SubAgent manager for creating and executing subagents."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from swecli.models.config import AppConfig

from .specs import CompiledSubAgent, SubAgentSpec
from .docker_execution import DockerSubAgentExecutor

logger = logging.getLogger(__name__)


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
        self._docker_executor = DockerSubAgentExecutor(self)

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
        return self._docker_executor.is_docker_available()

    def _get_spec_for_subagent(self, name: str) -> SubAgentSpec | None:
        """Get the SubAgentSpec for a registered subagent."""
        from .agents import ALL_SUBAGENTS
        return next((s for s in ALL_SUBAGENTS if s["name"] == name), None)

    # Delegated methods to DockerSubAgentExecutor

    def _extract_input_files(self, task: str, local_working_dir: Path) -> list[Path]:
        return self._docker_executor.extract_input_files(task, local_working_dir)

    def _extract_github_info(self, task: str) -> tuple[str, str, str] | None:
        return self._docker_executor.extract_github_info(task)

    def _copy_files_to_docker(self, container_name: str, files: list[Path], workspace_dir: str, ui_callback: Any = None) -> dict[str, str]:
        return self._docker_executor.copy_files_to_docker(container_name, files, workspace_dir, ui_callback)

    def _rewrite_task_for_docker(self, task: str, input_files: list[Path], workspace_dir: str) -> str:
        return self._docker_executor.rewrite_task_for_docker(task, input_files, workspace_dir)

    def _create_docker_path_sanitizer(self, workspace_dir: str, local_dir: str, image_name: str, container_id: str):
        return self._docker_executor._create_docker_path_sanitizer(workspace_dir, local_dir, image_name, container_id)

    def create_docker_nested_callback(self, ui_callback: Any, subagent_name: str, workspace_dir: str, image_name: str, container_id: str, local_dir: str | None = None) -> Any:
        return self._docker_executor.create_docker_nested_callback(ui_callback, subagent_name, workspace_dir, image_name, container_id, local_dir)

    def execute_with_docker_handler(self, name: str, task: str, deps: SubAgentDeps, docker_handler: Any, ui_callback: Any = None, container_id: str = "", image_name: str = "", workspace_dir: str = "/workspace", description: str | None = None) -> dict[str, Any]:
        return self._docker_executor.execute_with_docker_handler(name, task, deps, docker_handler, ui_callback, container_id, image_name, workspace_dir, description)

    def _extract_task_description(self, task: str) -> str:
        return self._docker_executor.extract_task_description(task)

    def _execute_with_docker(self, name: str, task: str, deps: SubAgentDeps, spec: SubAgentSpec, ui_callback: Any = None, task_monitor: Any = None, show_spawn_header: bool = True, local_output_dir: Path | None = None) -> dict[str, Any]:
        return self._docker_executor.execute_with_docker(name, task, deps, spec, ui_callback, task_monitor, show_spawn_header, local_output_dir)

    def _copy_files_from_docker(self, container_name: str, workspace_dir: str, local_dir: Path, spec: SubAgentSpec | None = None, ui_callback: Any = None) -> None:
        self._docker_executor.copy_files_from_docker(container_name, workspace_dir, local_dir, spec, ui_callback)

    def execute_subagent(
        self,
        name: str,
        task: str,
        deps: SubAgentDeps,
        ui_callback: Any = None,
        task_monitor: Any = None,
        working_dir: Any = None,
        docker_handler: Any = None,
        path_mapping: dict[str, str] | None = None,
        show_spawn_header: bool = True,
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
            path_mapping: Mapping of Docker paths to local paths for local-only tools.
                         Used to remap paths when tools like read_pdf run locally.
            show_spawn_header: Whether to show the Spawn[] header. Set to False when
                              called via tool_registry (react_executor already showed it).

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
                        show_spawn_header=show_spawn_header,
                        local_output_dir=Path(working_dir) if working_dir else None,
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
            # Pass path_mapping to remap Docker paths to local paths for local-only tools
            from swecli.core.docker.tool_handler import DockerToolRegistry
            tool_registry = DockerToolRegistry(
                docker_handler,
                local_registry=self._tool_registry,
                path_mapping=path_mapping,
            )
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
            import logging
            _logger = logging.getLogger(__name__)
            _logger.info(f"Creating SwecliAgent with tool_registry type: {type(tool_registry).__name__}")
            _logger.info(f"  docker_handler is None: {docker_handler is None}")
            _logger.info(f"  working_dir: {working_dir}")

            agent = SwecliAgent(
                config=self._get_subagent_config(spec),
                tool_registry=tool_registry,
                mode_manager=self._mode_manager,
                working_dir=working_dir if working_dir is not None else self._working_dir,
            )
            # Apply system prompt override
            if spec.get("system_prompt"):
                base_prompt = spec["system_prompt"]
                # When running in Docker, inject Docker context into system prompt
                if docker_handler is not None:
                    docker_preamble = f"""## CRITICAL: Docker Environment

YOU ARE RUNNING INSIDE A DOCKER CONTAINER.

Working directory: {working_dir}
All file operations execute inside the container.

FILE PATHS - VERY IMPORTANT:
- CORRECT: `pyproject.toml`, `src/model.py`, `config.yaml`
- WRONG: `/Users/.../file.py`, `/home/.../file.py`

NEVER use absolute paths like /Users/, /home/, /var/.
ALWAYS use relative paths (just the filename or relative path like src/file.py).

"""
                    agent.system_prompt = docker_preamble + base_prompt
                else:
                    agent.system_prompt = base_prompt
        else:
            agent = compiled["agent"]

        # Create nested callback wrapper if parent callback provided
        # If ui_callback is already a NestedUICallback, use it directly (avoids double-wrapping)
        # For Docker subagents, caller should use create_docker_nested_callback() first
        nested_callback = None
        if ui_callback is not None:
            from swecli.ui_textual.nested_callback import NestedUICallback
            if isinstance(ui_callback, NestedUICallback):
                # Already nested (e.g., from create_docker_nested_callback), use directly
                nested_callback = ui_callback
            else:
                # Wrap in NestedUICallback for proper nesting display
                # No path_sanitizer for local subagents - Docker subagents should
                # use create_docker_nested_callback() before calling execute_subagent()
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
