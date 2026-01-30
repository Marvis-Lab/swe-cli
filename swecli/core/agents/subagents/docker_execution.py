"""Docker execution executor for subagents."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import SubAgentManager, SubAgentDeps
    from .specs import SubAgentSpec

logger = logging.getLogger(__name__)


class DockerSubAgentExecutor:
    """Handles Docker-based execution for subagents."""

    def __init__(self, manager: SubAgentManager):
        """Initialize the Docker executor.

        Args:
            manager: The parent SubAgentManager instance.
        """
        self.manager = manager

    def is_docker_available(self) -> bool:
        """Check if Docker is available on the system."""
        return shutil.which("docker") is not None

    def execute(
        self,
        name: str,
        task: str,
        deps: SubAgentDeps,
        spec: SubAgentSpec,
        ui_callback: Any = None,
        task_monitor: Any = None,
        show_spawn_header: bool = True,
        local_output_dir: Path | None = None,
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
            show_spawn_header: Whether to show the Spawn[] header. Set to False when
                called via tool_registry (react_executor already showed it).
            local_output_dir: Local directory where files should be copied after Docker
                execution. If None, uses manager._working_dir or cwd.

        Returns:
            Result dict with content, success, and messages
        """
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
        local_working_dir = local_output_dir or (
            Path(self.manager._working_dir) if self.manager._working_dir else Path.cwd()
        )

        deployment = None
        loop = None
        nested_callback = None

        # Show Spawn header only for direct invocations (e.g., /paper2code)
        # When called via tool_registry, react_executor already showed the header
        spawn_args = None
        if show_spawn_header:
            spawn_args = {
                "subagent_type": name,
                "description": self.manager._extract_task_description(task),
            }
            if ui_callback and hasattr(ui_callback, "on_tool_call"):
                ui_callback.on_tool_call("spawn_subagent", spawn_args)

        try:
            # Create Docker deployment first to get container name
            # (container name is generated in __init__, before start())
            deployment = DockerDeployment(config=docker_config)

            # Extract container ID (last 8 chars of container name)
            # Container name format: "swecli-runtime-a1b2c3d4"
            container_id = deployment._container_name.split("-")[-1]

            # Create nested callback wrapper with container info using standardized interface
            # This ensures docker_start, docker_copy, and all subagent tool calls
            # appear properly nested under the Spawn[subagent_name] parent
            nested_callback = self.create_nested_callback(
                ui_callback=ui_callback,
                subagent_name=name,
                workspace_dir=workspace_dir,
                image_name=docker_config.image,
                container_id=container_id,
                local_dir=str(local_working_dir),
            )

            # Show Docker start as a tool call with spinner (using nested callback)
            if nested_callback and hasattr(nested_callback, 'on_tool_call'):
                nested_callback.on_tool_call("docker_start", {"image": docker_config.image})

            # Run async start in sync context - use a single event loop for the whole operation
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(deployment.start())

            # Show Docker start completion (using nested callback)
            if nested_callback and hasattr(nested_callback, 'on_tool_result'):
                nested_callback.on_tool_result("docker_start", {"image": docker_config.image}, {
                    "success": True,
                    "output": docker_config.image,
                })

            # Create workspace directory in Docker container
            # (some images like uv don't have /workspace by default)
            loop.run_until_complete(
                deployment.runtime.run(f"mkdir -p {workspace_dir}")
            )

            # Create Docker tool handler with local registry fallback for tools like read_pdf
            runtime = deployment.runtime
            shell_init = docker_config.shell_init if hasattr(docker_config, 'shell_init') else ""
            docker_handler = DockerToolHandler(
                runtime,
                workspace_dir=workspace_dir,
                shell_init=shell_init,
            )

            # Extract input files from task (PDFs, images, etc.)
            input_files = self.extract_input_files(task, local_working_dir)

            # Copy input files into Docker container using docker cp
            # Returns mapping of Docker paths to local paths for local-only tools
            # Note: Individual docker_copy calls will show progress for each file
            path_mapping: dict[str, str] = {}
            if input_files:
                path_mapping = self.copy_files_to_docker(
                    deployment._container_name,
                    input_files,
                    workspace_dir,
                    nested_callback,  # Use nested callback for proper nesting
                )

            # Rewrite task to use Docker paths
            docker_task = self.rewrite_task_for_docker(task, input_files, workspace_dir)

            # Execute subagent with Docker tools (local_registry passed for fallback)
            # Pass nested_callback - execute_subagent will detect it's already nested
            result = self.manager.execute_subagent(
                name=name,
                task=docker_task,  # Use rewritten task with Docker paths
                deps=deps,
                ui_callback=nested_callback,  # Already nested, will be used directly
                task_monitor=task_monitor,
                working_dir=workspace_dir,
                docker_handler=docker_handler,
                path_mapping=path_mapping,  # For local-only tool path remapping
                show_spawn_header=False,  # Already shown (or handled by show_spawn_header arg)
            )

            # Copy generated files from Docker to local working directory
            if result.get("success"):
                self.copy_files_from_docker(
                    container_name=deployment._container_name,
                    workspace_dir=workspace_dir,
                    local_dir=local_working_dir,
                    spec=spec,
                    ui_callback=nested_callback,
                )

            # Show Spawn completion only if we showed the header
            if spawn_args and ui_callback and hasattr(ui_callback, "on_tool_result"):
                ui_callback.on_tool_result("spawn_subagent", spawn_args, {
                    "success": result.get("success", True),
                })

            return result

        except Exception as e:
            import traceback
            # Stop the docker_start spinner by reporting failure
            if nested_callback and hasattr(nested_callback, 'on_tool_result'):
                nested_callback.on_tool_result("docker_start", {"image": docker_config.image}, {
                    "success": False,
                    "error": str(e),
                })
            # Show Spawn failure only if we showed the header
            if spawn_args and ui_callback and hasattr(ui_callback, "on_tool_result"):
                ui_callback.on_tool_result("spawn_subagent", spawn_args, {
                    "success": False,
                    "error": str(e),
                })
            return {
                "success": False,
                "error": f"Docker execution failed: {str(e)}\n{traceback.format_exc()}",
                "content": "",
            }
        finally:
            # Show Docker stop as a tool call (matching docker_start pattern)
            if deployment is not None and nested_callback and hasattr(nested_callback, 'on_tool_call'):
                nested_callback.on_tool_call("docker_stop", {"container": deployment._container_name[:12]})

            # Always stop the container
            if deployment is not None and loop is not None:
                try:
                    loop.run_until_complete(deployment.stop())
                except Exception:
                    pass  # Ignore cleanup errors

                # Show Docker stop completion with container ID
                if nested_callback and hasattr(nested_callback, 'on_tool_result'):
                    container_id = deployment._container_name
                    nested_callback.on_tool_result("docker_stop", {"container": container_id}, {"success": True, "output": container_id})

            # Close the loop after all async operations
            if loop is not None:
                try:
                    loop.close()
                except Exception:
                    pass

    def extract_input_files(self, task: str, local_working_dir: Path) -> list[Path]:
        """Extract DOCUMENT file paths referenced in the task.

        Only extracts PDF, DOC, DOCX - formats that can contain research papers.
        Images (PNG, JPEG, SVG) and data files (CSV) are NOT extracted.

        Args:
            task: The task description string
            local_working_dir: Local working directory to resolve relative paths

        Returns:
            List of existing document file paths to copy into Docker
        """
        files: list[Path] = []
        seen: set[str] = set()  # Track by resolved filename to avoid duplicates

        # Only document formats (PDF, DOC, DOCX)
        doc_pattern = r'pdf|docx?'

        # Pattern 1: @filename (e.g., @paper.pdf)
        at_mentions = re.findall(rf'@([\w\-\.]+\.(?:{doc_pattern}))\b', task, re.I)
        for filename in at_mentions:
            path = local_working_dir / filename
            if path.exists() and path.is_file() and path.name not in seen:
                files.append(path)
                seen.add(path.name)

        # Pattern 2: Quoted file paths (e.g., "paper.pdf", 'paper.pdf', `paper.pdf`)
        quoted_paths = re.findall(
            rf'["\'\`]([^"\'\`]+\.(?:{doc_pattern}))["\'\`]',
            task,
            re.I
        )
        for p in quoted_paths:
            path = Path(p) if Path(p).is_absolute() else local_working_dir / p
            if path.exists() and path.is_file() and path.name not in seen:
                files.append(path)
                seen.add(path.name)

        # Pattern 3: Unquoted document filenames (e.g., "PDF paper.pdf")
        unquoted_docs = re.findall(
            rf'(?:^|[\s(,])([^\s"\'()<>]+\.(?:{doc_pattern}))\b',
            task,
            re.I
        )
        for filename in unquoted_docs:
            path = Path(filename) if Path(filename).is_absolute() else local_working_dir / filename
            if path.exists() and path.is_file() and path.name not in seen:
                files.append(path)
                seen.add(path.name)

        # Pattern 4: Stems without extension (e.g., "paper 2303.11366v4" without .pdf)
        # Match alphanumeric+dots patterns that could be paper IDs (e.g., arXiv IDs)
        # Then check if a corresponding .pdf/.doc/.docx exists
        stem_pattern = r'(?:^|[\s(,])(\d[\w\.\-]+v\d+|\d{4}\.\d+(?:v\d+)?)\b'
        stems = re.findall(stem_pattern, task, re.I)
        for stem in stems:
            # Try adding document extensions
            for ext in ['pdf', 'PDF', 'docx', 'DOCX', 'doc', 'DOC']:
                candidate = local_working_dir / f"{stem}.{ext}"
                if candidate.exists() and candidate.is_file():
                    # Check if this file was already found (use resolved name)
                    if candidate.name not in seen:
                        files.append(candidate)
                        seen.add(candidate.name)
                    break

        return files

    def copy_files_to_docker(
        self,
        container_name: str,
        files: list[Path],
        workspace_dir: str,
        ui_callback: Any = None,
    ) -> dict[str, str]:
        """Copy local files into Docker container using docker cp.

        Args:
            container_name: Docker container name or ID
            files: List of local file paths to copy
            workspace_dir: Target directory in Docker container
            ui_callback: Optional UI callback for progress display

        Returns:
            Mapping of Docker paths to local paths (for local-only tool remapping)
        """
        path_mapping: dict[str, str] = {}

        for local_file in files:
            # Show copy progress - use on_nested_tool_call for proper display
            if ui_callback:
                if hasattr(ui_callback, 'on_nested_tool_call'):
                    # Direct nested callback - use proper method
                    ui_callback.on_nested_tool_call(
                        "docker_copy",
                        {"file": local_file.name},
                        depth=getattr(ui_callback, '_depth', 1),
                        parent=getattr(ui_callback, '_context', 'Docker'),
                    )
                elif hasattr(ui_callback, 'on_tool_call'):
                    ui_callback.on_tool_call("docker_copy", {"file": local_file.name})

            try:
                docker_target = f"{workspace_dir}/{local_file.name}"
                docker_path = f"{container_name}:{docker_target}"

                # Use docker cp for reliable file transfer (handles any size/binary)
                result = subprocess.run(
                    ["docker", "cp", str(local_file), docker_path],
                    capture_output=True,
                    text=True,
                    timeout=60.0,
                )

                if result.returncode != 0:
                    raise RuntimeError(f"docker cp failed: {result.stderr}")

                # Store mapping: Docker path → local path
                path_mapping[docker_target] = str(local_file)

                # Show completion - use on_nested_tool_result for proper display
                if ui_callback:
                    result_data = {"success": True, "output": f"Copied to {docker_target}"}
                    if hasattr(ui_callback, 'on_nested_tool_result'):
                        ui_callback.on_nested_tool_result(
                            "docker_copy",
                            {"file": local_file.name},
                            result_data,
                            depth=getattr(ui_callback, '_depth', 1),
                            parent=getattr(ui_callback, '_context', 'Docker'),
                        )
                    elif hasattr(ui_callback, 'on_tool_result'):
                        ui_callback.on_tool_result("docker_copy", {"file": local_file.name}, result_data)

            except Exception as e:
                if ui_callback:
                    result_data = {"success": False, "error": str(e)}
                    if hasattr(ui_callback, 'on_nested_tool_result'):
                        ui_callback.on_nested_tool_result(
                            "docker_copy",
                            {"file": local_file.name},
                            result_data,
                            depth=getattr(ui_callback, '_depth', 1),
                            parent=getattr(ui_callback, '_context', 'Docker'),
                        )
                    elif hasattr(ui_callback, 'on_tool_result'):
                        ui_callback.on_tool_result("docker_copy", {"file": local_file.name}, result_data)

        return path_mapping

    def rewrite_task_for_docker(
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
            Task with paths rewritten to Docker paths, including Docker context
        """
        new_task = task

        # Remove phrases that hint at local filesystem
        new_task = re.sub(r'\blocal\s+', '', new_task, flags=re.IGNORECASE)
        new_task = re.sub(r'\bin this repo\b', f'in {workspace_dir}', new_task, flags=re.IGNORECASE)
        new_task = re.sub(r'\bthis repo\b', workspace_dir, new_task, flags=re.IGNORECASE)

        # Replace any reference to the local working directory with workspace
        local_working_dir = self.manager._working_dir
        if local_working_dir:
            local_dir_str = str(local_working_dir)
            # Replace the local directory path with workspace
            new_task = new_task.replace(local_dir_str, workspace_dir)
            # Also try without trailing slash
            new_task = new_task.replace(local_dir_str.rstrip("/"), workspace_dir)

        for local_file in input_files:
            docker_path = f"{workspace_dir}/{local_file.name}"
            # Replace @filename with Docker path
            new_task = new_task.replace(f"@{local_file.name}", docker_path)
            # Also replace any absolute local paths
            new_task = new_task.replace(str(local_file), docker_path)
            # Replace plain filename references (be careful to avoid partial matches)
            # Use word boundary matching by checking surrounding chars
            new_task = re.sub(
                rf'\b{re.escape(local_file.name)}\b',
                docker_path,
                new_task
            )

        # Prepend Docker context with strong emphasis
        docker_context = f"""## CRITICAL: Docker Environment

YOU ARE RUNNING INSIDE A DOCKER CONTAINER.

Working directory: {workspace_dir}
All file paths MUST be relative (e.g., `file.py`, `src/file.py`) or start with {workspace_dir}/.

NEVER use paths like:
- /Users/...
- /home/...
- Any absolute path outside {workspace_dir}

ALWAYS use paths like:
- pyproject.toml
- src/model.py
- config.yaml

Use ONLY the filename or relative path for all file operations.

"""
        return docker_context + new_task

    def create_path_sanitizer(
        self,
        workspace_dir: str,
        local_dir: str,
        image_name: str,
        container_id: str,
    ):
        """Create a path sanitizer for Docker mode UI display.

        Converts local paths to Docker workspace paths with container prefix.

        Args:
            workspace_dir: The Docker workspace directory (e.g., /workspace)
            local_dir: The local working directory
            image_name: Full Docker image name
            container_id: Short container ID

        Returns:
            A callable that sanitizes paths for display
        """
        # Extract short image name: "ghcr.io/astral-sh/uv:python3.11-bookworm" → "uv"
        short_image = image_name.split("/")[-1].split(":")[0]
        prefix = f"[{short_image}:{container_id}]:"

        def sanitize(path: str) -> str:
            # If path starts with local_dir, replace with workspace_dir
            if path.startswith(local_dir):
                relative = path[len(local_dir):].lstrip("/")
                docker_path = f"{workspace_dir}/{relative}" if relative else workspace_dir
                return f"{prefix}{docker_path}"

            # Handle Docker-internal absolute paths (e.g., /workspace/..., /testbed/...)
            # These are paths the LLM outputs when running inside Docker
            if path.startswith(workspace_dir):
                return f"{prefix}{path}"

            # Fallback: extract filename from other absolute paths
            match = re.match(r'^(/Users/|/home/|/var/|/tmp/).+/([^/]+)$', path)
            if match:
                return f"{prefix}{workspace_dir}/{match.group(2)}"

            # Convert relative paths to full Docker paths
            if not path.startswith("/"):
                clean_path = path.lstrip("./")
                if not clean_path:
                    return f"{prefix}{workspace_dir}"
                return f"{prefix}{workspace_dir}/{clean_path}"

            return path
        return sanitize

    def create_nested_callback(
        self,
        ui_callback: Any,
        subagent_name: str,
        workspace_dir: str,
        image_name: str,
        container_id: str,
        local_dir: str | None = None,
    ) -> Any:
        """Create NestedUICallback with Docker path sanitizer for consistent display.

        Args:
            ui_callback: Parent UI callback to wrap
            subagent_name: Name of the subagent
            workspace_dir: Docker workspace path
            image_name: Full Docker image name
            container_id: Short container ID
            local_dir: Local directory for path remapping (optional)

        Returns:
            NestedUICallback wrapped with Docker path sanitizer, or None if ui_callback is None
        """
        if ui_callback is None:
            return None

        from swecli.ui_textual.nested_callback import NestedUICallback

        # Use existing create_path_sanitizer
        path_sanitizer = self.create_path_sanitizer(
            workspace_dir=workspace_dir,
            local_dir=local_dir or str(self.manager._working_dir or Path.cwd()),
            image_name=image_name,
            container_id=container_id,
        )

        return NestedUICallback(
            parent_callback=ui_callback,
            parent_context=subagent_name,
            depth=1,
            path_sanitizer=path_sanitizer,
        )

    def execute_with_handler(
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

        Args:
            name: Subagent name
            task: Task prompt for subagent
            deps: SubAgentDeps
            docker_handler: Pre-configured DockerToolHandler
            ui_callback: UI callback for display
            container_id: Docker container ID (last 8 chars)
            image_name: Docker image name
            workspace_dir: Workspace directory inside container
            description: Description for Spawn header (defaults to task excerpt)

        Returns:
            Result dict with success, content, etc.
        """
        compiled = self.manager._agents.get(name)
        if not compiled:
            return {"success": False, "error": f"Unknown subagent: {name}"}

        # Extract description from task if not provided
        if description is None:
            description = self.manager._extract_task_description(task)

        # Show Spawn header
        spawn_args = {
            "subagent_type": name,
            "description": description,
        }
        if ui_callback and hasattr(ui_callback, "on_tool_call"):
            ui_callback.on_tool_call("spawn_subagent", spawn_args)

        # Create nested callback with Docker context
        nested_callback = self.create_nested_callback(
            ui_callback=ui_callback,
            subagent_name=name,
            workspace_dir=workspace_dir,
            image_name=image_name,
            container_id=container_id,
        )

        try:
            # Execute subagent with nested callback and docker handler
            result = self.manager.execute_subagent(
                name=name,
                task=task,
                deps=deps,
                ui_callback=nested_callback,
                docker_handler=docker_handler,
                show_spawn_header=False,  # Already shown
            )

            # Show Spawn result
            if ui_callback and hasattr(ui_callback, "on_tool_result"):
                success = isinstance(result, str) or result.get("success", True)
                ui_callback.on_tool_result("spawn_subagent", spawn_args, {
                    "success": success,
                    "output": result.get("content", "") if isinstance(result, dict) else str(result),
                })

            return result

        except Exception as e:
            if ui_callback and hasattr(ui_callback, "on_tool_result"):
                ui_callback.on_tool_result("spawn_subagent", spawn_args, {
                    "success": False,
                    "error": str(e),
                })
            return {"success": False, "error": str(e)}

    def copy_files_from_docker(
        self,
        container_name: str,
        workspace_dir: str,
        local_dir: Path,
        spec: SubAgentSpec | None = None,
        ui_callback: Any = None,
    ) -> None:
        """Copy generated files from Docker container to local directory using docker cp.

        Args:
            container_name: Docker container name/ID
            workspace_dir: Path inside container (e.g., /workspace)
            local_dir: Local directory to copy files to
            spec: SubAgentSpec for copy configuration
            ui_callback: UI callback for progress display
        """
        recursive = spec.get("copy_back_recursive", True) if spec else True

        if not recursive:
            return  # Skip copy if not configured

        try:
            # Show copy operation in UI
            if ui_callback and hasattr(ui_callback, 'on_tool_call'):
                ui_callback.on_tool_call("docker_copy_back", {
                    "from": f"{container_name}:{workspace_dir}",
                    "to": str(local_dir),
                })

            # Use docker cp to copy entire workspace recursively
            # The "/." at the end copies contents without creating workspace folder
            result = subprocess.run(
                ["docker", "cp", f"{container_name}:{workspace_dir}/.", str(local_dir)],
                capture_output=True,
                text=True,
                timeout=120.0,
            )

            if result.returncode == 0:
                logger.info(f"Copied workspace from Docker to {local_dir}")
                if ui_callback and hasattr(ui_callback, 'on_tool_result'):
                    ui_callback.on_tool_result("docker_copy_back", {}, {
                        "success": True,
                        "output": f"Copied to {local_dir}",
                    })
            else:
                logger.warning(f"docker cp failed: {result.stderr}")
                if ui_callback and hasattr(ui_callback, 'on_tool_result'):
                    ui_callback.on_tool_result("docker_copy_back", {}, {
                        "success": False,
                        "error": result.stderr,
                    })

        except subprocess.TimeoutExpired:
            logger.error("docker cp timed out after 120 seconds")
        except Exception as e:
            logger.error(f"Failed to copy from Docker: {e}")
