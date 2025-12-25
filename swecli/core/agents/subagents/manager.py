"""SubAgent manager for creating and executing subagents."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
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
            from swecli.core.docker.tool_handler import DockerToolRegistry
            tool_registry = DockerToolRegistry(docker_handler)
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

        # Display spawn tool call BEFORE creating nested callback
        # This ensures the Spawn line appears before any nested tool calls
        if ui_callback is not None and hasattr(ui_callback, "on_tool_call"):
            # Build a short description for display (first line of task)
            first_line = task.split("\n")[0].strip()
            if len(first_line) > 100:
                first_line = first_line[:97] + "..."
            ui_callback.on_tool_call("spawn_subagent", {
                "subagent_type": name,
                "description": first_line,
            })
            # Small delay to ensure UI renders before nested calls start
            import time
            time.sleep(0.05)

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
