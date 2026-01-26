"""Append-only progress log for Ralph iterations."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ProgressEntry(BaseModel):
    """A single progress log entry from one iteration."""

    timestamp: datetime = Field(default_factory=datetime.now)
    story_id: str = Field(..., description="User story ID that was worked on")
    summary: str = Field(..., description="What was implemented")
    files_changed: list[str] = Field(default_factory=list, description="List of changed files")
    learnings: list[str] = Field(
        default_factory=list, description="Patterns and learnings for future iterations"
    )
    success: bool = Field(default=True, description="Whether the iteration succeeded")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class RalphProgressLog:
    """Append-only progress tracker for Ralph iterations.

    This class manages progress.txt, which persists learnings and patterns
    between iterations to help future AI instances understand the codebase.
    """

    PATTERNS_HEADER = "## Codebase Patterns"
    ENTRY_SEPARATOR = "---"

    def __init__(self, path: Path):
        """Initialize progress log.

        Args:
            path: Path to progress.txt file
        """
        self.path = path
        self._patterns: list[str] = []
        self._entries: list[str] = []

        if path.exists():
            self._parse_existing()

    def _parse_existing(self) -> None:
        """Parse existing progress.txt file."""
        content = self.path.read_text()

        # Extract patterns section
        patterns_match = re.search(
            rf"{re.escape(self.PATTERNS_HEADER)}\n(.*?)(?=\n## |\n{self.ENTRY_SEPARATOR}|\Z)",
            content,
            re.DOTALL,
        )
        if patterns_match:
            patterns_text = patterns_match.group(1).strip()
            self._patterns = [
                line.lstrip("- ").strip()
                for line in patterns_text.split("\n")
                if line.strip() and line.strip().startswith("-")
            ]

    def initialize(self) -> None:
        """Initialize a new progress.txt file."""
        content = f"""# Ralph Progress Log
Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{self.PATTERNS_HEADER}
(Patterns discovered during implementation will be added here)

{self.ENTRY_SEPARATOR}
"""
        self.path.write_text(content)

    def append_entry(self, entry: ProgressEntry) -> None:
        """Append a new progress entry.

        Args:
            entry: Progress entry to append

        Note:
            This is append-only - never overwrites existing content.
        """
        timestamp = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            f"\n## [{timestamp}] - {entry.story_id}",
        ]

        if entry.success:
            lines.append(f"- {entry.summary}")
        else:
            lines.append(f"- FAILED: {entry.summary}")
            if entry.error:
                lines.append(f"- Error: {entry.error}")

        if entry.files_changed:
            lines.append("- Files changed:")
            for f in entry.files_changed:
                lines.append(f"  - {f}")

        if entry.learnings:
            lines.append("- **Learnings for future iterations:**")
            for learning in entry.learnings:
                lines.append(f"  - {learning}")

        lines.append(f"\n{self.ENTRY_SEPARATOR}")

        # Append to file
        with open(self.path, "a") as f:
            f.write("\n".join(lines))

    def add_pattern(self, pattern: str) -> None:
        """Add a new codebase pattern to the patterns section.

        Args:
            pattern: Pattern description to add

        Note:
            Only adds if pattern doesn't already exist.
        """
        if pattern in self._patterns:
            return

        self._patterns.append(pattern)
        self._update_patterns_section()

    def _update_patterns_section(self) -> None:
        """Update the patterns section in the file."""
        if not self.path.exists():
            return

        content = self.path.read_text()

        # Build new patterns section
        patterns_content = "\n".join(f"- {p}" for p in self._patterns)
        new_patterns = f"{self.PATTERNS_HEADER}\n{patterns_content}\n"

        # Replace existing patterns section
        pattern = rf"{re.escape(self.PATTERNS_HEADER)}\n.*?(?=\n## |\n{self.ENTRY_SEPARATOR})"
        if re.search(pattern, content, re.DOTALL):
            content = re.sub(pattern, new_patterns, content, flags=re.DOTALL)
        else:
            # Insert after header if no patterns section exists
            header_end = content.find("\n---")
            if header_end > 0:
                content = content[:header_end] + f"\n{new_patterns}" + content[header_end:]

        self.path.write_text(content)

    def get_codebase_patterns(self) -> list[str]:
        """Get all discovered codebase patterns.

        Returns:
            List of pattern descriptions
        """
        return self._patterns.copy()

    def get_context_for_agent(self) -> str:
        """Get progress context for injecting into agent prompts.

        Returns:
            Formatted string with patterns and recent learnings
        """
        lines = []

        if self._patterns:
            lines.append("## Codebase Patterns (from previous iterations)")
            for pattern in self._patterns:
                lines.append(f"- {pattern}")
            lines.append("")

        return "\n".join(lines)

    def get_iteration_count(self) -> int:
        """Get the number of iterations completed.

        Returns:
            Number of progress entries
        """
        if not self.path.exists():
            return 0

        content = self.path.read_text()
        # Count entry headers
        return len(re.findall(r"## \[\d{4}-\d{2}-\d{2}", content))
