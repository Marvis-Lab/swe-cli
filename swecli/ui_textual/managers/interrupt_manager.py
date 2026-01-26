"""Centralized interrupt/escape handling for the Textual UI.

This module provides a unified InterruptManager that:
1. Tracks what is currently active (prompt, tool, panel, thinking)
2. Provides consistent cancel behavior based on active state
3. Ensures proper cleanup (spinners, UI state)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from textual.app import App


class InterruptState(Enum):
    """States that affect how ESC/interrupt is handled."""

    IDLE = auto()
    EXIT_CONFIRMATION = auto()
    APPROVAL_PROMPT = auto()
    ASK_USER_PROMPT = auto()
    MODEL_PICKER = auto()
    AGENT_WIZARD = auto()
    SKILL_WIZARD = auto()
    AUTOCOMPLETE = auto()
    PROCESSING_THINKING = auto()
    PROCESSING_TOOL = auto()
    PROCESSING_PARALLEL_TOOLS = auto()


@dataclass
class InterruptContext:
    """Context information for the current interrupt state."""

    state: InterruptState
    tool_name: Optional[str] = None
    tool_names: List[str] = field(default_factory=list)
    spinner_ids: List[str] = field(default_factory=list)
    controller_ref: Optional[Any] = None


class InterruptManager:
    """Centralized manager for interrupt/escape key handling.

    This manager tracks the current UI state and ensures ESC key
    presses are handled consistently across different contexts:

    - Autocomplete visible: dismiss autocomplete only
    - Modal/wizard active: cancel the modal
    - Processing: interrupt the running operation
    - Exit confirmation: clear confirmation mode

    Thread Safety:
    - All public methods are thread-safe via RLock
    - State stack supports nested contexts (e.g., approval during subagent)
    """

    def __init__(self, app: "App") -> None:
        """Initialize the InterruptManager.

        Args:
            app: The Textual App instance
        """
        self.app = app
        self._lock = threading.RLock()
        self._current_state = InterruptState.IDLE
        self._context: Optional[InterruptContext] = None
        self._state_stack: List[InterruptContext] = []

    @property
    def current_state(self) -> InterruptState:
        """Get the current interrupt state."""
        with self._lock:
            return self._current_state

    @property
    def context(self) -> Optional[InterruptContext]:
        """Get the current context."""
        with self._lock:
            return self._context

    def enter_state(
        self,
        state: InterruptState,
        tool_name: Optional[str] = None,
        tool_names: Optional[List[str]] = None,
        spinner_ids: Optional[List[str]] = None,
        controller_ref: Optional[Any] = None,
    ) -> None:
        """Push current state and enter new state.

        Args:
            state: The new state to enter
            tool_name: Optional single tool name (for PROCESSING_TOOL)
            tool_names: Optional list of tool names (for PROCESSING_PARALLEL_TOOLS)
            spinner_ids: Optional list of active spinner IDs
            controller_ref: Optional reference to the active controller
        """
        with self._lock:
            # Push current context to stack if we have one
            if self._context is not None:
                self._state_stack.append(self._context)

            self._current_state = state
            self._context = InterruptContext(
                state=state,
                tool_name=tool_name,
                tool_names=tool_names or [],
                spinner_ids=spinner_ids or [],
                controller_ref=controller_ref,
            )

    def exit_state(self) -> None:
        """Pop and restore previous state."""
        with self._lock:
            if self._state_stack:
                self._context = self._state_stack.pop()
                self._current_state = self._context.state
            else:
                self._current_state = InterruptState.IDLE
                self._context = None

    def is_in_state(self, *states: InterruptState) -> bool:
        """Check if currently in any of the given states.

        Args:
            *states: States to check against

        Returns:
            True if current state matches any of the given states
        """
        with self._lock:
            return self._current_state in states

    def handle_interrupt(self) -> bool:
        """Handle ESC key press based on current state.

        Returns:
            True if the interrupt was consumed (no further handling needed),
            False if the caller should handle the interrupt
        """
        from swecli.ui_textual.debug_logger import debug_log
        debug_log("InterruptManager", "handle_interrupt called")
        debug_log("InterruptManager", f"current_state={self._current_state}")

        # First, check for autocomplete (highest priority)
        if self._has_autocomplete():
            debug_log("InterruptManager", "Has autocomplete, dismissing")
            return self._dismiss_autocomplete()

        # Check for active controllers by querying the app
        # This allows controllers that don't explicitly register to still be handled
        if self._cancel_any_active_controller():
            debug_log("InterruptManager", "Cancelled an active controller")
            return True

        with self._lock:
            state = self._current_state

            # Check for exit confirmation mode
            if state == InterruptState.EXIT_CONFIRMATION:
                debug_log("InterruptManager", "Clearing exit confirmation")
                return self._clear_exit_confirmation()

            # Processing states - handled by caller (action_interrupt)
            if state in (
                InterruptState.PROCESSING_THINKING,
                InterruptState.PROCESSING_TOOL,
                InterruptState.PROCESSING_PARALLEL_TOOLS,
            ):
                # Cleanup spinners but let caller handle the actual interrupt
                debug_log("InterruptManager", "Processing state, cleaning spinners, returning False")
                self.cleanup_spinners()
                return False

            # IDLE state - nothing to handle
            debug_log("InterruptManager", "IDLE state, returning False")
            return False

    def handle_cancel(self) -> bool:
        """Handle Ctrl+C based on current state.

        This is similar to handle_interrupt but may have different
        behavior for some states.

        Returns:
            True if the cancel was consumed, False otherwise
        """
        # For now, delegate to handle_interrupt
        # Controllers can check for Ctrl+C vs ESC if needed
        return self.handle_interrupt()

    def cleanup_spinners(self) -> None:
        """Stop all active spinners tracked in current context."""
        spinner_ids = []
        with self._lock:
            if self._context:
                spinner_ids = list(self._context.spinner_ids)

        # Stop spinners outside lock to avoid deadlock
        if hasattr(self.app, "spinner_service"):
            spinner_service = self.app.spinner_service
            for spinner_id in spinner_ids:
                if spinner_service.is_active(spinner_id):
                    spinner_service.stop(spinner_id, success=False)

    def stop_all_spinners(self, success: bool = False) -> None:
        """Stop all active spinners via SpinnerService.

        Args:
            success: Whether to mark spinners as successful
        """
        if hasattr(self.app, "spinner_service"):
            self.app.spinner_service.stop_all(immediate=True)

    def add_spinner_id(self, spinner_id: str) -> None:
        """Track a spinner ID in the current context.

        Args:
            spinner_id: The spinner ID to track
        """
        with self._lock:
            if self._context:
                self._context.spinner_ids.append(spinner_id)

    def remove_spinner_id(self, spinner_id: str) -> None:
        """Remove a spinner ID from tracking.

        Args:
            spinner_id: The spinner ID to remove
        """
        with self._lock:
            if self._context and spinner_id in self._context.spinner_ids:
                self._context.spinner_ids.remove(spinner_id)

    # -------------------------------------------------------------------------
    # Internal handlers
    # -------------------------------------------------------------------------

    def _has_autocomplete(self) -> bool:
        """Check if autocomplete is currently visible."""
        if hasattr(self.app, "input_field"):
            input_field = self.app.input_field
            completions = getattr(input_field, "_completions", None)
            return bool(completions)
        return False

    def _dismiss_autocomplete(self) -> bool:
        """Dismiss autocomplete popup.

        Returns:
            True if autocomplete was dismissed
        """
        if hasattr(self.app, "input_field"):
            input_field = self.app.input_field
            if hasattr(input_field, "_dismiss_autocomplete"):
                input_field._dismiss_autocomplete()
                return True
        return False

    def _cancel_any_active_controller(self) -> bool:
        """Check for and cancel any active controller.

        This checks controllers by querying them directly rather than
        relying on state tracking. This is more robust for controllers
        that don't explicitly register with the InterruptManager.

        Returns:
            True if a controller was cancelled
        """
        from swecli.ui_textual.debug_logger import debug_log

        # Check approval controller
        approval = getattr(self.app, "_approval_controller", None)
        approval_active = approval and getattr(approval, "active", False)
        debug_log("InterruptManager", f"approval_controller active={approval_active}")
        if approval_active:
            if hasattr(self.app, "_approval_cancel"):
                self.app._approval_cancel()
                return True

        # Check ask-user controller
        ask_user = getattr(self.app, "_ask_user_controller", None)
        ask_user_active = ask_user and getattr(ask_user, "active", False)
        debug_log("InterruptManager", f"ask_user_controller active={ask_user_active}")
        if ask_user_active:
            if hasattr(self.app, "_ask_user_cancel"):
                self.app._ask_user_cancel()
                return True

        # Check model picker
        model_picker = getattr(self.app, "_model_picker", None)
        model_picker_active = model_picker and getattr(model_picker, "active", False)
        debug_log("InterruptManager", f"model_picker active={model_picker_active}")
        if model_picker_active:
            if hasattr(self.app, "_model_picker_cancel"):
                self.app._model_picker_cancel()
                return True

        # Check agent wizard
        agent_creator = getattr(self.app, "_agent_creator", None)
        agent_creator_active = agent_creator and getattr(agent_creator, "active", False)
        debug_log("InterruptManager", f"agent_creator active={agent_creator_active}")
        if agent_creator_active:
            if hasattr(self.app, "_agent_wizard_cancel"):
                self.app._agent_wizard_cancel()
                return True

        # Check skill wizard
        skill_creator = getattr(self.app, "_skill_creator", None)
        skill_creator_active = skill_creator and getattr(skill_creator, "active", False)
        debug_log("InterruptManager", f"skill_creator active={skill_creator_active}")
        if skill_creator_active:
            if hasattr(self.app, "_skill_wizard_cancel"):
                self.app._skill_wizard_cancel()
                return True

        debug_log("InterruptManager", "No active controllers")
        return False

    def _cancel_active_controller(self) -> bool:
        """Cancel the active modal controller based on tracked state.

        Returns:
            True if a controller was cancelled
        """
        with self._lock:
            context = self._context
            state = self._current_state

        if context is None:
            return False

        # Try to use controller_ref if available
        controller = context.controller_ref
        if controller and hasattr(controller, "cancel"):
            controller.cancel()
            return True

        # Fall back to app method lookup based on state
        method_map = {
            InterruptState.APPROVAL_PROMPT: "_approval_cancel",
            InterruptState.ASK_USER_PROMPT: "_ask_user_cancel",
            InterruptState.MODEL_PICKER: "_model_picker_cancel",
            InterruptState.AGENT_WIZARD: "_agent_wizard_cancel",
            InterruptState.SKILL_WIZARD: "_skill_wizard_cancel",
        }

        method_name = method_map.get(state)
        if method_name and hasattr(self.app, method_name):
            getattr(self.app, method_name)()
            return True

        return False

    def _clear_exit_confirmation(self) -> bool:
        """Clear exit confirmation mode.

        Returns:
            True if exit confirmation was cleared
        """
        if hasattr(self.app, "_cancel_exit_confirmation"):
            self.app._cancel_exit_confirmation()
            return True
        return False


__all__ = [
    "InterruptManager",
    "InterruptState",
    "InterruptContext",
]
