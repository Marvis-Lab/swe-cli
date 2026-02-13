from __future__ import annotations

import logging
from typing import Any

from .base import DockerToolBase

logger = logging.getLogger(__name__)


class FileOperationsTool(DockerToolBase):
    async def read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Read a file from inside the Docker container."""
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

    async def write_file(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Write a file inside the Docker container."""
        # Accept both "file_path" (standard) and "path" (legacy) argument names
        path = arguments.get("file_path") or arguments.get("path", "")
        content = arguments.get("content", "")

        logger.info(f"DockerToolHandler.write_file called with path: {path}")

        if not path:
            return {
                "success": False,
                "error": "file_path or path is required",
                "output": None,
            }

        # Translate path to container path
        container_path = self._translate_path(path)
        logger.info(f"  → Translated to Docker path: {container_path}")

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

    async def edit_file(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Edit a file inside the Docker container using sed-like replacement."""
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

            # Check if old_text exists (with fuzzy matching fallback)
            found, actual_old_text = self._find_content(content, old_text)
            if not found:
                return {
                    "success": False,
                    "error": f"old_text not found in {container_path}",
                    "output": None,
                }

            # Perform replacement using actual matched content
            new_content = content.replace(actual_old_text, new_text, 1)

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

    def _find_content(self, original: str, old_content: str) -> tuple[bool, str]:
        """Find content in file, with fallback to normalized matching."""
        # Try exact match first (fast path)
        if old_content in original:
            return (True, old_content)

        # Normalize: strip each line, normalize line endings
        def normalize(s: str) -> str:
            lines = s.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            return "\n".join(line.strip() for line in lines)

        norm_old = normalize(old_content)
        norm_original = normalize(original)

        # If normalized content not found, give up
        if norm_old not in norm_original:
            return (False, old_content)

        # Find actual content in original by line matching
        old_lines = [ln.strip() for ln in old_content.split("\n") if ln.strip()]
        if not old_lines:
            return (False, old_content)

        original_lines = original.split("\n")

        # Find start line that matches first stripped line
        for i, line in enumerate(original_lines):
            if line.strip() == old_lines[0]:
                # Try to match all subsequent lines
                matched_lines = []
                j = 0  # Index into old_lines
                for k in range(i, min(i + len(old_lines) * 2, len(original_lines))):
                    if j >= len(old_lines):
                        break
                    if original_lines[k].strip() == old_lines[j]:
                        matched_lines.append(original_lines[k])
                        j += 1

                if j == len(old_lines):
                    # Found all lines - reconstruct actual content
                    actual = "\n".join(matched_lines)
                    # Check if we need trailing newline
                    if actual in original:
                        return (True, actual)
                    if actual + "\n" in original:
                        return (True, actual + "\n")

        return (False, old_content)
