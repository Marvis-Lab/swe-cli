"""Handler for capturing model reasoning/thinking content."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class ThinkingBlock:
    """A single block of thinking content."""

    id: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class ThinkingHandler:
    """Handler for think tool - captures model reasoning.

    This handler manages thinking content that the model produces
    when using the 'think' tool to reason through complex problems.
    The content can be displayed in the UI with dark gray styling
    and visibility can be toggled via hotkey.
    """

    def __init__(self):
        """Initialize thinking handler with empty state."""
        self._blocks: List[ThinkingBlock] = []
        self._next_id = 1
        self._visible = True

    def add_thinking(self, content: str) -> dict:
        """Add a thinking block.

        Args:
            content: The reasoning/thinking content from the model

        Returns:
            Result dict with success status and special _thinking_content key
        """
        if not content or not content.strip():
            return {
                "success": False,
                "error": "Thinking content cannot be empty",
                "output": "",  # Empty string, not None (APIs require string)
            }

        block_id = f"think-{self._next_id}"
        self._next_id += 1

        block = ThinkingBlock(id=block_id, content=content.strip())
        self._blocks.append(block)

        return {
            "success": True,
            "output": "",  # Empty string - thinking shown via UI callback, not tool result
            "thinking_id": block_id,
            "_thinking_content": content.strip(),  # Special key for UI callback
        }

    def get_all_thinking(self) -> List[ThinkingBlock]:
        """Get all thinking blocks for current turn.

        Returns:
            List of ThinkingBlock objects
        """
        return list(self._blocks)

    def get_latest_thinking(self) -> Optional[ThinkingBlock]:
        """Get the most recent thinking block.

        Returns:
            The latest ThinkingBlock or None if empty
        """
        return self._blocks[-1] if self._blocks else None

    def clear(self) -> None:
        """Clear all thinking blocks.

        Should be called when a new user message is processed
        to reset the thinking state for the new turn.
        """
        self._blocks.clear()
        self._next_id = 1

    def toggle_visibility(self) -> bool:
        """Toggle global visibility of thinking content.

        Returns:
            New visibility state (True = visible)
        """
        self._visible = not self._visible
        return self._visible

    @property
    def is_visible(self) -> bool:
        """Check if thinking content should be displayed.

        Returns:
            True if thinking content should be shown
        """
        return self._visible

    @property
    def block_count(self) -> int:
        """Get the number of thinking blocks.

        Returns:
            Number of thinking blocks stored
        """
        return len(self._blocks)
