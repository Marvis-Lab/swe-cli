"""Mode management for controlling operation behavior."""

from enum import Enum
from typing import Callable, Optional

from swecli.models.operation import OperationType


class OperationMode(str, Enum):
    """Operation modes."""

    NORMAL = "normal"  # Interactive execution with approval for each operation
    PLAN = "plan"  # Planning only, no execution


# Type alias for mode change callbacks
ModeChangeCallback = Callable[["OperationMode"], None]


class ModeManager:
    """Manager for operation modes and plan storage."""

    def __init__(self, default_mode: OperationMode = OperationMode.NORMAL):
        """Initialize mode manager.

        Args:
            default_mode: Initial mode
        """
        self._current_mode = default_mode
        self._operation_count = 0  # Track operations in normal mode

        # Mode change callbacks for unified mode switching
        self._mode_change_callbacks: list[ModeChangeCallback] = []

        # Plan storage for auto-execute workflow
        self._pending_plan: Optional[str] = None
        self._plan_steps: list[str] = []
        self._plan_goal: Optional[str] = None

    def add_mode_change_listener(self, callback: ModeChangeCallback) -> None:
        """Register a callback to be invoked when mode changes.

        Args:
            callback: Function that receives the new OperationMode
        """
        self._mode_change_callbacks.append(callback)

    def remove_mode_change_listener(self, callback: ModeChangeCallback) -> None:
        """Remove a previously registered mode change callback.

        Args:
            callback: The callback to remove
        """
        if callback in self._mode_change_callbacks:
            self._mode_change_callbacks.remove(callback)

    @property
    def current_mode(self) -> OperationMode:
        """Get current operation mode."""
        return self._current_mode

    def set_mode(self, mode: OperationMode) -> None:
        """Set operation mode.

        Args:
            mode: Mode to set

        Note:
            All registered mode change listeners are notified when the mode changes.
        """
        old_mode = self._current_mode
        self._current_mode = mode

        # Reset operation counter when switching to normal
        if mode == OperationMode.NORMAL:
            self._operation_count = 0

        # Notify listeners if mode actually changed
        if old_mode != mode:
            for callback in self._mode_change_callbacks:
                callback(mode)

    def is_approval_required(
        self,
        operation: OperationType,
        is_dangerous: bool = False,
    ) -> bool:
        """Check if approval is required for an operation.

        Args:
            operation: Type of operation
            is_dangerous: Whether operation is considered dangerous

        Returns:
            True if approval is required
        """
        # Plan mode never executes, always requires "approval" to plan
        if self._current_mode == OperationMode.PLAN:
            return True

        # Normal mode: all operations require approval (interactive workflow)
        if self._current_mode == OperationMode.NORMAL:
            return True

        return True  # Default to requiring approval

    def needs_approval(self, operation) -> bool:
        """Check if an operation needs approval.

        Args:
            operation: Operation object

        Returns:
            True if approval is required
        """
        # Import here to avoid circular dependency
        from swecli.models.operation import Operation
        import re

        if isinstance(operation, Operation):
            # Smart danger detection for bash commands
            is_dangerous = False

            if operation.type == OperationType.BASH_EXECUTE:
                # Only dangerous if matches dangerous patterns
                # Command is stored in 'target' field for bash operations
                command = operation.target or operation.parameters.get("command", "") or ""

                # Dangerous patterns (from bash_tool.py)
                dangerous_patterns = [
                    r"rm\s+-rf\s+/",  # Delete root
                    r"sudo",  # Privileged execution
                    r"chmod\s+-R\s+777",  # Permissive permissions
                    r":\(\)\{\s*:\|\:&\s*\};:",  # Fork bomb
                    r"mv\s+/",  # Move root directories
                    r">\s*/dev/sd[a-z]",  # Write to disk directly
                    r"dd\s+if=.*of=/dev",  # Disk operations
                    r"curl.*\|\s*bash",  # Download and execute
                    r"wget.*\|\s*bash",  # Download and execute
                    r"mkfs",  # Format filesystem
                    r"fdisk",  # Disk partitioning
                ]

                for pattern in dangerous_patterns:
                    if re.search(pattern, command, re.IGNORECASE):
                        is_dangerous = True
                        break

            return self.is_approval_required(operation.type, is_dangerous)
        else:
            # Fallback for OperationType
            return self.is_approval_required(operation)

    def record_operation(self) -> None:
        """Record that an operation was performed (for normal mode tracking)."""
        if self._current_mode == OperationMode.NORMAL:
            self._operation_count += 1

    def get_operation_count(self) -> int:
        """Get count of operations performed in normal mode."""
        return self._operation_count

    def get_mode_indicator(self) -> str:
        """Get a visual indicator for the current mode.

        Returns:
            String indicator for display
        """
        indicators = {
            OperationMode.NORMAL: "[NORMAL]",
            OperationMode.PLAN: "[PLAN]",
        }
        return indicators.get(self._current_mode, "[UNKNOWN]")

    def get_mode_description(self) -> str:
        """Get description of current mode.

        Returns:
            Mode description
        """
        descriptions = {
            OperationMode.NORMAL: "Interactive execution with approval for each operation",
            OperationMode.PLAN: "Planning only, no execution",
        }
        return descriptions.get(self._current_mode, "Unknown mode")

    # Plan storage methods for auto-execute workflow

    def store_plan(
        self,
        plan_text: str,
        steps: list[str],
        goal: Optional[str] = None,
    ) -> None:
        """Store an approved plan for execution.

        Args:
            plan_text: The full plan text
            steps: List of implementation steps
            goal: The plan goal (optional)
        """
        self._pending_plan = plan_text
        self._plan_steps = steps
        self._plan_goal = goal

    def get_pending_plan(self) -> tuple[Optional[str], list[str], Optional[str]]:
        """Return pending plan, steps, and goal.

        Returns:
            Tuple of (plan_text, steps, goal)
        """
        return self._pending_plan, self._plan_steps, self._plan_goal

    def has_pending_plan(self) -> bool:
        """Check if there's a pending plan awaiting approval.

        Returns:
            True if there's a pending plan
        """
        return self._pending_plan is not None

    def clear_plan(self) -> None:
        """Clear the pending plan after execution or cancellation."""
        self._pending_plan = None
        self._plan_steps = []
        self._plan_goal = None
