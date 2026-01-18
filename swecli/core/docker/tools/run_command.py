from __future__ import annotations

import logging
from typing import Any

from .base import DockerToolBase

logger = logging.getLogger(__name__)


class RunCommandTool(DockerToolBase):
    def __init__(self, runtime, workspace_dir: str, shell_init: str = ""):
        super().__init__(runtime, workspace_dir)
        self.shell_init = shell_init

    async def execute(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Execute a command inside the Docker container."""
        from swecli.core.docker.models import BashAction

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
