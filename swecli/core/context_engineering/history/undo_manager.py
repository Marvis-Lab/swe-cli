"""Undo system for rolling back operations."""

from swecli.models.operation import Operation


class UndoManager:
    """Manager for undoing operations (Stubbed - functionality removed)."""

    def __init__(self, max_history: int = 50):
        """Initialize undo manager.

        Args:
            max_history: Maximum number of operations to track
        """
        self.max_history = max_history

    def record_operation(self, operation: Operation) -> None:
        """Record an operation for potential undo.

        Args:
            operation: Operation to record
        """
        pass
