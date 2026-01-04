"""Execution manager for LLM calls and tool execution."""

import json
import random
import time
from typing import TYPE_CHECKING, Optional, Any, Tuple, Dict

from swecli.ui_textual.utils.tool_display import format_tool_call
from swecli.repl.constants.thinking_verbs import THINKING_VERBS

if TYPE_CHECKING:
    from rich.console import Console
    from swecli.core.runtime import ModeManager, ConfigManager
    from swecli.core.runtime.approval import ApprovalManager
    from swecli.core.context_engineering.history import SessionManager, UndoManager
    from swecli.ui_textual.formatters_internal.output_formatter import OutputFormatter


class ExecutionManager:
    """Handles LLM execution loop and tool execution."""

    def __init__(
        self,
        console: "Console",
        session_manager: "SessionManager",
        mode_manager: "ModeManager",
        output_formatter: "OutputFormatter",
    ):
        """Initialize execution manager.

        Args:
            console: Rich console for output
            session_manager: Session manager
            mode_manager: Mode manager
            output_formatter: Output formatter
        """
        self.console = console
        self.session_manager = session_manager
        self.mode_manager = mode_manager
        self.output_formatter = output_formatter

        # Interrupt support - track current task monitor
        self._current_task_monitor: Optional[Any] = None

        # Last operation tracking
        self._last_operation_summary = "—"
        self._last_error = None

    @property
    def last_operation_summary(self) -> str:
        """Get summary of last operation."""
        return self._last_operation_summary

    @property
    def last_error(self) -> Optional[str]:
        """Get last error message."""
        return self._last_error

    @last_error.setter
    def last_error(self, value: Optional[str]):
        """Set last error message."""
        self._last_error = value

    def request_interrupt(self) -> bool:
        """Request interrupt of currently running task (LLM call or tool execution).

        Returns:
            True if interrupt was requested, False if no task is running
        """
        if self._current_task_monitor is not None:
            self._current_task_monitor.request_interrupt()
            return True
        return False

    def call_llm_with_progress(self, agent, messages: list, task_monitor: Any) -> Tuple[Dict[str, Any], int]:
        """Call LLM with progress display.

        Args:
            agent: Agent to use
            messages: Message history
            task_monitor: Task monitor for tracking

        Returns:
            Tuple of (response, latency_ms)
        """
        from swecli.ui_textual.components.task_progress import TaskProgressDisplay

        # Get random thinking verb
        thinking_verb = random.choice(THINKING_VERBS)
        task_monitor.start(thinking_verb, initial_tokens=0)

        # Track current monitor for interrupt support
        self._current_task_monitor = task_monitor

        # Create progress display with live updates
        progress = TaskProgressDisplay(self.console, task_monitor)
        progress.start()

        # Give display a moment to render before HTTP call
        time.sleep(0.05)

        try:
            # Call LLM
            started = time.perf_counter()
            response = agent.call_llm(messages, task_monitor=task_monitor)
            latency_ms = int((time.perf_counter() - started) * 1000)

            # Get LLM description
            message_payload = response.get("message", {}) or {}
            llm_description = response.get("content", message_payload.get("content", ""))

            # Stop progress and show final status
            progress.stop()
            progress.print_final_status(replacement_message=llm_description)

            return response, latency_ms
        finally:
            # Clear current monitor
            self._current_task_monitor = None

    def execute_tool_call(
        self,
        tool_call: dict,
        tool_registry,
        approval_manager: "ApprovalManager",
        undo_manager: "UndoManager",
        ui_callback=None,
    ) -> dict:
        """Execute a single tool call.

        Args:
            tool_call: Tool call specification
            tool_registry: Tool registry
            approval_manager: Approval manager
            undo_manager: Undo manager
            ui_callback: Optional UI callback for nested tool call display

        Returns:
            Tool execution result
        """
        from swecli.core.runtime.monitoring import TaskMonitor
        from swecli.ui_textual.components.task_progress import TaskProgressDisplay
        from swecli.core.runtime import OperationMode

        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])

        # Format tool call display
        tool_call_display = format_tool_call(tool_name, tool_args)

        # Create task monitor for interrupt support
        tool_monitor = TaskMonitor()
        tool_monitor.start(tool_call_display, initial_tokens=0)

        # Track current monitor for interrupt support
        self._current_task_monitor = tool_monitor

        # Show progress in PLAN mode
        if self.mode_manager.current_mode == OperationMode.PLAN:
            tool_progress = TaskProgressDisplay(self.console, tool_monitor)
            tool_progress.start()
        else:
            # In NORMAL mode, show static symbol before approval
            self.console.print(f"\n⏺ [cyan]{tool_call_display}[/cyan]")
            tool_progress = TaskProgressDisplay(self.console, tool_monitor)
            tool_progress.start()

        try:
            # Execute tool with interrupt support and ui_callback for nested display
            result = tool_registry.execute_tool(
                tool_name,
                tool_args,
                mode_manager=self.mode_manager,
                approval_manager=approval_manager,
                undo_manager=undo_manager,
                task_monitor=tool_monitor,
                session_manager=self.session_manager,
                ui_callback=ui_callback,
            )

            # Update state
            self._last_operation_summary = tool_call_display
            if result.get("success"):
                self._last_error = None
            else:
                self._last_error = result.get("error", "Tool execution failed")

            # Stop progress if it was started
            if tool_progress:
                tool_progress.stop()

            # Display result (skip for spawn_subagent since it shows separate_response)
            if not result.get("separate_response"):
                panel = self.output_formatter.format_tool_result(tool_name, tool_args, result)
                self.console.print(panel)

            return result
        finally:
            # Clear current monitor
            self._current_task_monitor = None
