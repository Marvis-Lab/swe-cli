"""Unified terminal box renderer for VS Code-style terminal output."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List

from rich.text import Text

from swecli.ui_textual.style_tokens import (
    BLUE_PATH,
    ERROR,
    GREEN_PROMPT,
    GREY,
    PANEL_BORDER,
    SUBTLE,
)
from swecli.ui_textual.utils.output_summarizer import summarize_output, get_expansion_hint


@dataclass
class TerminalBoxConfig:
    """Configuration for a terminal box."""

    command: str = ""
    working_dir: str = "."
    depth: int = 0
    is_error: bool = False
    box_width: int = 80


class TerminalBoxRenderer:
    """Renders VS Code-style terminal boxes with consistent styling.

    Supports both complete (all-at-once) and streaming (incremental) rendering.
    All methods return Text objects - caller controls when/how to write them.
    """

    # Color constants for terminal box elements
    POINTER_COLOR = GREY
    PATH_COLOR = BLUE_PATH
    PROMPT_COLOR = GREEN_PROMPT
    COMMAND_COLOR = GREY
    ERROR_COLOR = ERROR
    BORDER_DEFAULT = PANEL_BORDER
    BORDER_ERROR = ERROR

    # Truncation settings by depth (head + tail lines shown)
    MAIN_AGENT_HEAD_LINES = 5
    MAIN_AGENT_TAIL_LINES = 5
    SUBAGENT_HEAD_LINES = 3
    SUBAGENT_TAIL_LINES = 3

    def __init__(self):
        """Initialize renderer."""
        pass

    # --- Utility methods ---

    @staticmethod
    def format_path(path: str) -> str:
        """Shorten path by replacing home directory with ~."""
        home = os.path.expanduser("~")
        if path.startswith(home):
            return "~" + path[len(home) :]
        return path

    @staticmethod
    def normalize_line(line: str) -> str:
        """Normalize: expand tabs, strip ANSI codes."""
        line = line.expandtabs(4)
        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
        return line

    def _get_border_color(self, config: TerminalBoxConfig) -> str:
        """Get border color based on error state."""
        return self.BORDER_ERROR if config.is_error else self.BORDER_DEFAULT

    def _get_indent(self, config: TerminalBoxConfig) -> str:
        """Get indentation string based on depth."""
        return "  " * config.depth

    def _get_content_width(self, box_width: int) -> int:
        """Get content width (space for text inside borders)."""
        return box_width - 5  # Space for "│  " (3) + " │" (2)

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


