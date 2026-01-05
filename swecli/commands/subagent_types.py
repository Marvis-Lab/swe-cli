"""Standard types for subagent commands.

This module defines common result and metadata types used across all subagent-powered
commands (paper2code, resolve-issue, etc.) to ensure consistent interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union


@dataclass
class OutputMetadata:
    """Metadata for commands that generate output files."""

    output_path: Path


@dataclass
class PatchMetadata:
    """Metadata for commands that generate patches."""

    patch_path: Path
    base_commit: Optional[str] = None


@dataclass
class PRMetadata:
    """Metadata for commands that create pull requests."""

    pr_url: str
    pr_number: int


@dataclass
class RepoMetadata:
    """Metadata for commands working with repositories."""

    repo_path: Path
    branch: Optional[str] = None


# Union of all metadata types for type-safe access
CommandMetadata = Union[OutputMetadata, PatchMetadata, PRMetadata, RepoMetadata, None]


@dataclass
class SubagentCommandResult:
    """Standard result for all subagent commands.

    This provides a consistent interface for command results, with typed metadata
    that varies by command type.

    Examples:
        # Paper2Code result
        result = SubagentCommandResult(
            success=True,
            message="Paper implemented in /path/to/project",
            metadata=OutputMetadata(output_path=Path("/path/to/project")),
        )

        # Resolve-Issue result with patch
        result = SubagentCommandResult(
            success=True,
            message="Issue resolved",
            metadata=PatchMetadata(
                patch_path=Path("issue-123.patch"),
                base_commit="abc1234",
            ),
        )

        # Resolve-Issue result with PR
        result = SubagentCommandResult(
            success=True,
            message="PR created",
            metadata=PRMetadata(pr_url="https://github.com/...", pr_number=456),
        )
    """

    success: bool
    message: str
    metadata: CommandMetadata = None
    artifact_paths: list[Path] = field(default_factory=list)
