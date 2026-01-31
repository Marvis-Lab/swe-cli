"""Unified terminal box renderer for VS Code-style terminal output."""

from __future__ import annotations

import re
from typing import List


class TerminalBoxRenderer:
    """Renders VS Code-style terminal boxes with consistent styling.

    Supports both complete (all-at-once) and streaming (incremental) rendering.
    All methods return Text objects - caller controls when/how to write them.
    """

    # Truncation settings by depth (head + tail lines shown)
    MAIN_AGENT_HEAD_LINES = 5
    MAIN_AGENT_TAIL_LINES = 5
    SUBAGENT_HEAD_LINES = 3
    SUBAGENT_TAIL_LINES = 3

    @staticmethod
    def normalize_line(line: str) -> str:
        """Normalize: expand tabs, strip ANSI codes."""
        line = line.expandtabs(4)
        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
        return line

    @staticmethod
    def truncate_lines_head_tail(
        lines: List[str],
        head_count: int,
        tail_count: int,
    ) -> tuple:
        """Split lines into head, tail, and count of hidden lines.

        Args:
            lines: All output lines
            head_count: Number of lines to keep from start
            tail_count: Number of lines to keep from end

        Returns:
            Tuple of (head_lines, tail_lines, hidden_count)
            If no truncation needed, returns (lines, [], 0)
        """
        total = len(lines)
        max_lines = head_count + tail_count

        if total <= max_lines:
            return (lines, [], 0)

        head = lines[:head_count]
        tail = lines[-tail_count:]
        hidden = total - max_lines

        return (head, tail, hidden)
