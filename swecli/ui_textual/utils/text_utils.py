"""Text processing utilities for the Textual UI."""

from __future__ import annotations

import re
from typing import Any


def truncate_tool_output(raw_result: Any, max_lines: int = 6, max_chars: int = 400) -> str:
    """Truncate tool output to reasonable size for display.

    Args:
        raw_result: The raw tool result to truncate
        max_lines: Maximum number of lines to show
        max_chars: Maximum characters per line

    Returns:
        Truncated output string
    """
    if not raw_result:
        return ""

    text = str(raw_result)
    lines = text.splitlines()

    if len(lines) <= max_lines:
        return text

    kept = lines[:max_lines]
    omitted = len(lines) - max_lines

    truncated_lines = []
    for line in kept:
        if len(line) > max_chars:
            truncated_lines.append(line[:max_chars] + "...")
        else:
            truncated_lines.append(line)

    truncated_lines.append(f"... ({omitted} more lines)")
    return "\n".join(truncated_lines)


def normalize_console_text(text: str) -> str:
    """Normalize console text by removing carriage returns.

    Args:
        text: Raw console text

    Returns:
        Normalized text
    """
    if not text:
        return text

    # Remove carriage returns only - preserve ANSI codes for AnsiDecoder
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    return normalized


def clean_tool_summary(summary: str) -> str:
    """Clean tool summary text for display.

    Args:
        summary: Raw summary text

    Returns:
        Cleaned summary text
    """
    if not summary:
        return summary

    # Remove extra whitespace
    cleaned = " ".join(summary.split())

    # Remove common prefixes
    prefixes = ["Result:", "Output:", "Success:"]
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].lstrip()

    return cleaned


def is_spinner_text(plain: str) -> bool:
    """Check if text is spinner animation text.

    Args:
        plain: Plain text to check

    Returns:
        True if text is spinner animation
    """
    if not plain:
        return False

    spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    stripped = plain.strip()

    # Check if it starts with a spinner character
    if any(stripped.startswith(char) for char in spinner_chars):
        return True

    # Check for common spinner patterns
    if re.match(r'^[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]\s+', stripped):
        return True

    return False


def is_spinner_tip(plain: str) -> bool:
    """Check if text is a spinner tip message.

    Args:
        plain: Plain text to check

    Returns:
        True if text is a spinner tip
    """
    if not plain:
        return False

    stripped = plain.strip().lower()

    # Common tip patterns
    tip_patterns = [
        "tip:",
        "hint:",
        "note:",
    ]

    return any(stripped.startswith(pattern) for pattern in tip_patterns)


__all__ = [
    "truncate_tool_output",
    "normalize_console_text",
    "clean_tool_summary",
    "is_spinner_text",
    "is_spinner_tip",
]
