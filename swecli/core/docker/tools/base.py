from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swecli.core.docker.remote_runtime import RemoteRuntime

logger = logging.getLogger(__name__)


class DockerToolBase:
    """Base class for Docker tools."""

    def __init__(self, runtime: RemoteRuntime, workspace_dir: str):
        self.runtime = runtime
        self.workspace_dir = workspace_dir

    def _translate_path(self, path: str) -> str:
        """Translate a host path to a container path.

        If the path is already absolute and starts with /workspace or /testbed, use as-is.
        Otherwise, assume it's relative to the workspace.
        """
        if not path:
            return self.workspace_dir

        # If it's already a container path, use as-is
        if path.startswith("/testbed") or path.startswith("/workspace"):
            return path

        # Relative path - prepend workspace (strip leading ./)
        if not path.startswith("/"):
            clean_path = path.lstrip("./")
            return f"{self.workspace_dir}/{clean_path}"

        # Absolute host path (e.g., /Users/.../file.py)
        # Extract just the filename - safest for Docker since we can't know
        # the original repo structure
        try:
            p = Path(path)
            return f"{self.workspace_dir}/{p.name}"
        except Exception:
            pass

        # Fallback: just use the path as-is under workspace
        return f"{self.workspace_dir}/{path}"
