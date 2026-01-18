from __future__ import annotations

from typing import Any

from .base import DockerToolBase


class SearchTool(DockerToolBase):
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Search for text in files inside the Docker container."""
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
