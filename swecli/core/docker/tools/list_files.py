from __future__ import annotations

from typing import Any

from .base import DockerToolBase


class ListFilesTool(DockerToolBase):
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """List files in a directory inside the Docker container."""
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
                error_msg = (
                    obs.failure_reason or obs.output or f"Directory not found: {container_path}"
                )
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
