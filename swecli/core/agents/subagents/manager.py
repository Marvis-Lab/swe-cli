"""SubAgent manager for creating and executing subagents."""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from swecli.models.config import AppConfig
from .docker_execution import DockerSubAgentExecutor
from .ask_user_handler import AskUserSubAgentHandler

from .specs import CompiledSubAgent, SubAgentSpec

logger = logging.getLogger(__name__)


class AgentSource(str, Enum):
    """Source of an agent definition."""
    BUILTIN = "builtin"
    USER_GLOBAL = "user-global"
    PROJECT = "project"


@dataclass
class AgentConfig:
    """Configuration for an agent (builtin or custom).

    Used for building Task tool descriptions and on-demand prompt assembly.
    """
    name: str
    description: str
    tools: list[str] | str | dict[str, list[str]] = field(default_factory=list)
    system_prompt: str | None = None
    skill_path: str | None = None  # For custom agents
    source: AgentSource = AgentSource.BUILTIN
    model: str | None = None

    def get_tool_list(self, all_tools: list[str]) -> list[str]:
        """Resolve tool specification to concrete list.

        Args:
            all_tools: List of all available tool names

        Returns:
            Resolved list of tool names for this agent
        """
        if self.tools == "*":
            return all_tools
        if isinstance(self.tools, list):
            return self.tools if self.tools else all_tools
        if isinstance(self.tools, dict) and "exclude" in self.tools:
            excluded = set(self.tools["exclude"])
            return [t for t in all_tools if t not in excluded]
        return all_tools


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

        # New executors
        self.docker_executor = DockerSubAgentExecutor(self)
        self.ask_user_handler = AskUserSubAgentHandler()

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

        # Create the subagent instance with tool filtering
        agent = SwecliAgent(
            config=self._get_subagent_config(spec),
            tool_registry=self._tool_registry,
            mode_manager=self._mode_manager,
            working_dir=self._working_dir,
            allowed_tools=tool_names,  # Pass tool filtering to agent
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

    def get_agent_configs(self) -> list[AgentConfig]:
        """Get all agent configurations for Task tool description.

        Returns:
            List of AgentConfig for all registered agents (builtin and custom)
        """
        from .agents import ALL_SUBAGENTS

        configs = []
        for spec in ALL_SUBAGENTS:
            config = AgentConfig(
                name=spec["name"],
                description=spec["description"],
                tools=spec.get("tools", []),
                system_prompt=spec.get("system_prompt"),
                source=AgentSource.BUILTIN,
                model=spec.get("model"),
            )
            configs.append(config)

        # Include custom agents (added via register_custom_agents)
        for name, compiled in self._agents.items():
            # Skip if already in configs (builtin)
            if any(c.name == name for c in configs):
                continue
            # This is a custom agent
            config = AgentConfig(
                name=name,
                description=compiled["description"],
                tools=compiled.get("tool_names", []),
                source=AgentSource.USER_GLOBAL,  # Will be updated by register_custom_agents
            )
            configs.append(config)

        return configs

    def build_task_tool_description(self) -> str:
        """Build spawn_subagent tool description from registered agents.

        Returns:
            Formatted description string for the spawn_subagent tool
        """
        lines = [
            "Spawn a specialized subagent to handle a specific task.",
            "",
            "Available agent types:",
        ]
        for config in self.get_agent_configs():
            lines.append(f"- **{config.name}**: {config.description}")
        lines.append("")
        lines.append("Use this tool when you need specialized capabilities or ")
        lines.append("want to delegate complex tasks to a focused agent.")
        return "\n".join(lines)

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

    def register_custom_agents(self, custom_agents: list[dict]) -> None:
        """Register custom agents from config files.

        Custom agents can be defined in:
        - ~/.swecli/agents.json or <project>/.swecli/agents.json (JSON format)
        - ~/.swecli/agents/*.md or <project>/.swecli/agents/*.md (Claude Code markdown format)

        Each agent definition can specify:
        - name: Unique agent name (required)
        - description: Human-readable description (optional)
        - tools: List of tool names, "*" for all, or {"exclude": [...]} (optional)
        - skillPath: Path to skill file to use as system prompt (optional, JSON format)
        - _system_prompt: Direct system prompt content (markdown format)
        - model: Model override for this agent (optional)

        Args:
            custom_agents: List of agent definitions from config files
        """
        for agent_def in custom_agents:
            name = agent_def.get("name")
            if not name:
                logger.warning("Skipping custom agent without name")
                continue

            # Skip if already registered (builtin takes priority)
            if name in self._agents:
                logger.debug(f"Custom agent '{name}' shadows builtin agent, skipping")
                continue

            # Build AgentConfig from definition
            config = AgentConfig(
                name=name,
                description=agent_def.get("description", f"Custom agent: {name}"),
                tools=agent_def.get("tools", "*"),
                skill_path=agent_def.get("skillPath"),
                source=AgentSource.USER_GLOBAL if agent_def.get("_source") == "user-global" else AgentSource.PROJECT,
                model=agent_def.get("model"),
            )

            # Check for direct system prompt (from markdown agent files)
            # or build from skill file
            if "_system_prompt" in agent_def:
                system_prompt = agent_def["_system_prompt"]
            else:
                system_prompt = self._build_custom_agent_prompt(config)

            # Create SubAgentSpec for registration
            spec: SubAgentSpec = {
                "name": name,
                "description": config.description,
                "system_prompt": system_prompt,
                "tools": config.get_tool_list(self._all_tool_names),
            }

            if config.model:
                spec["model"] = config.model

            # Register the agent
            self.register_subagent(spec)
            logger.info(f"Registered custom agent: {name} (source: {config.source.value})")

    def _build_custom_agent_prompt(self, config: AgentConfig) -> str:
        """Build system prompt for a custom agent.

        Args:
            config: AgentConfig with skill_path or other config

        Returns:
            System prompt string
        """
        if config.skill_path:
            # Load skill content from file
            from pathlib import Path
            skill_path = Path(config.skill_path).expanduser()
            if skill_path.exists():
                try:
                    content = skill_path.read_text(encoding="utf-8")
                    # Strip YAML frontmatter if present
                    if content.startswith("---"):
                        import re
                        content = re.sub(r"^---\n.*?\n---\n*", "", content, flags=re.DOTALL)
                    return content
                except Exception as e:
                    logger.warning(f"Failed to load skill file {skill_path}: {e}")

        # Default prompt for custom agents
        return f"""You are a custom agent named "{config.name}".

{config.description}

Complete the task given to you, using available tools as needed.
Be thorough and provide a clear summary when done."""

    def _get_spec_for_subagent(self, name: str) -> SubAgentSpec | None:
        """Get the SubAgentSpec for a registered subagent."""
        from .agents import ALL_SUBAGENTS
        return next((s for s in ALL_SUBAGENTS if s["name"] == name), None)

    def create_docker_nested_callback(
        self,
        ui_callback: Any,
        subagent_name: str,
        workspace_dir: str,
        image_name: str,
        container_id: str,
        local_dir: str | None = None,
    ) -> Any:
        """Create NestedUICallback with Docker path sanitizer for consistent display.

        This is the STANDARD INTERFACE for Docker subagent UI context.
        Use this method whenever executing a subagent inside Docker.

        Args:
            ui_callback: Parent UI callback to wrap
            subagent_name: Name of the subagent (e.g., "Code-Explorer", "Web-clone")
            workspace_dir: Docker workspace path (e.g., "/workspace", "/testbed")
            image_name: Full Docker image name (e.g., "ghcr.io/astral-sh/uv:python3.11")
            container_id: Short container ID (e.g., "a1b2c3d4")
            local_dir: Local directory for path remapping (optional)

        Returns:
            NestedUICallback wrapped with Docker path sanitizer, or None if ui_callback is None
        """
        return self.docker_executor.create_nested_callback(
            ui_callback=ui_callback,
            subagent_name=subagent_name,
            workspace_dir=workspace_dir,
            image_name=image_name,
            container_id=container_id,
            local_dir=local_dir,
        )

    def execute_with_docker_handler(
        self,
        name: str,
        task: str,
        deps: SubAgentDeps,
        docker_handler: Any,
        ui_callback: Any = None,
        container_id: str = "",
        image_name: str = "",
        workspace_dir: str = "/workspace",
        description: str | None = None,
    ) -> dict[str, Any]:
        """Execute subagent with pre-configured Docker handler.

        Use this when you need custom Docker setup (e.g., clone repo, install deps)
        before subagent execution, but still want standardized UI display.

        This provides:
        - Spawn header: Spawn[name](description)
        - Nested callback with Docker path prefix: [image:containerid]:/workspace/...
        - Consistent result display

        Args:
            name: Subagent name (e.g., "Code-Explorer", "Web-clone")
            task: Task prompt for subagent
            deps: SubAgentDeps with mode_manager, approval_manager, undo_manager
            docker_handler: Pre-configured DockerToolHandler
            ui_callback: UI callback for display
            container_id: Docker container ID (last 8 chars) for path prefix
            image_name: Docker image name for path prefix
            workspace_dir: Workspace directory inside container
            description: Description for Spawn header (defaults to task excerpt)

        Returns:
            Result dict with success, content, etc.
        """
        return self.docker_executor.execute_with_handler(
            name=name,
            task=task,
            deps=deps,
            docker_handler=docker_handler,
            ui_callback=ui_callback,
            container_id=container_id,
            image_name=image_name,
            workspace_dir=workspace_dir,
            description=description,
        )

    def _extract_task_description(self, task: str) -> str:
        """Extract a short description from the task for Spawn header display.

        Args:
            task: The full task description

        Returns:
            A short description suitable for display
        """
        # Look for PDF filename in task
        if ".pdf" in task.lower():
            import re
            match = re.search(r'([^\s/]+\.pdf)', task, re.IGNORECASE)
            if match:
                return f"Implement {match.group(1)}"
        # Default: first line, truncated
        first_line = task.split('\n')[0][:50]
        if len(task.split('\n')[0]) > 50:
            return first_line + "..."
        return first_line

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
        tool_call_id: str | None = None,
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
            tool_call_id: Optional unique tool call ID for parent context tracking.
                         When provided, used as parent_context in NestedUICallback
                         to enable individual agent tracking in parallel display.

        Returns:
            Result dict with content, success, and messages
        """
        # SPECIAL CASE: ask-user subagent
        # This is a built-in that shows UI panel instead of running LLM
        if name == "ask-user":
            return self.ask_user_handler.execute(task, ui_callback)

        # Block Docker subagents in PLAN mode - they require write access
        if docker_handler is None:
            spec = self._get_spec_for_subagent(name)
            if spec is not None and spec.get("docker_config") is not None:
                from swecli.core.runtime.mode_manager import OperationMode
                if deps.mode_manager and deps.mode_manager.current_mode == OperationMode.PLAN:
                    return {
                        "success": False,
                        "error": f"Cannot spawn '{name}' in PLAN mode. Docker subagents require write access. "
                                 "Switch to NORMAL mode with '/mode normal' or Shift+Tab to use this agent.",
                        "content": "",
                    }

        # Auto-detect Docker execution for subagents with docker_config
        # Only trigger if docker_handler is not already provided (to avoid recursion)
        if docker_handler is None:
            spec = self._get_spec_for_subagent(name)
            if spec is not None and spec.get("docker_config") is not None:
                if self.docker_executor.is_docker_available():
                    # Execute with Docker lifecycle management
                    return self.docker_executor.execute(
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

        # Note: UI callback notifications for single agents are handled by
        # TextualUICallback.on_tool_call() and on_tool_result() for spawn_subagent

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

        # Determine if we're in PLAN mode (affects agent selection)
        from swecli.core.runtime.mode_manager import OperationMode
        is_plan_mode = deps.mode_manager and deps.mode_manager.current_mode == OperationMode.PLAN

        # If working_dir, docker_handler, or PLAN mode requires a new agent instance
        # PLAN mode needs PlanningAgent with read-only tools
        if working_dir is not None or docker_handler is not None or is_plan_mode:
            from swecli.core.agents import SwecliAgent
            from swecli.core.agents.planning_agent import PlanningAgent
            from swecli.core.agents.components import PLANNING_TOOLS
            from .agents import ALL_SUBAGENTS

            # Find the spec for this subagent
            spec = next((s for s in ALL_SUBAGENTS if s["name"] == name), None)
            if spec is None:
                return {
                    "success": False,
                    "error": f"Spec not found for subagent '{name}'",
                    "content": "",
                }

            # Get allowed tools from spec (for subagent tool filtering)
            # In PLAN mode, restrict to read-only planning tools
            if is_plan_mode:
                spec_tools = set(spec.get("tools", self._all_tool_names))
                allowed_tools = list(spec_tools & PLANNING_TOOLS)
            else:
                allowed_tools = spec.get("tools", self._all_tool_names)

            # Create agent - PlanningAgent in PLAN mode, SwecliAgent otherwise
            import logging
            _logger = logging.getLogger(__name__)
            agent_type = "PlanningAgent" if is_plan_mode else "SwecliAgent"
            # _logger.info(f"Creating {agent_type} with tool_registry type: {type(tool_registry).__name__}")
            # _logger.info(f"  docker_handler is None: {docker_handler is None}")
            # _logger.info(f"  working_dir: {working_dir}")
            # _logger.info(f"  is_plan_mode: {is_plan_mode}")
            # _logger.info(f"  allowed_tools: {allowed_tools}")

            if is_plan_mode:
                # Use PlanningAgent with read-only tools
                agent = PlanningAgent(
                    config=self._get_subagent_config(spec),
                    tool_registry=tool_registry,
                    mode_manager=self._mode_manager,
                    working_dir=working_dir if working_dir is not None else self._working_dir,
                )
            else:
                agent = SwecliAgent(
                    config=self._get_subagent_config(spec),
                    tool_registry=tool_registry,
                    mode_manager=self._mode_manager,
                    working_dir=working_dir if working_dir is not None else self._working_dir,
                    allowed_tools=allowed_tools,  # Pass tool filtering
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
                # Use tool_call_id as parent_context for individual agent tracking
                # in parallel display (falls back to name for single agent calls)
                # No path_sanitizer for local subagents - Docker subagents should
                # use create_docker_nested_callback() before calling execute_subagent()
                import sys
                # print(f"[DEBUG MANAGER] Creating NestedUICallback: tool_call_id={tool_call_id!r}, name={name!r}, parent_context={tool_call_id or name!r}", file=sys.stderr)
                nested_callback = NestedUICallback(
                    parent_callback=ui_callback,
                    parent_context=tool_call_id or name,
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
        # 1. Notify start of parallel execution
        agent_names = [name for name, _ in tasks]
        if ui_callback and hasattr(ui_callback, 'on_parallel_agents_start'):
            ui_callback.on_parallel_agents_start(agent_names)

        # 2. Execute in parallel with completion tracking
        async def execute_with_tracking(name: str, task: str) -> dict[str, Any]:
            """Execute a single subagent and report completion."""
            result = await self.execute_subagent_async(name, task, deps, ui_callback)
            success = result.get("success", True) if isinstance(result, dict) else True
            if ui_callback and hasattr(ui_callback, 'on_parallel_agent_complete'):
                ui_callback.on_parallel_agent_complete(name, success)
            return result

        coroutines = [
            execute_with_tracking(name, task)
            for name, task in tasks
        ]
        results = await asyncio.gather(*coroutines)

        # 3. Notify completion of all parallel agents
        if ui_callback and hasattr(ui_callback, 'on_parallel_agents_done'):
            ui_callback.on_parallel_agents_done()

        return results
