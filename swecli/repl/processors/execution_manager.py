"""Execution manager for handling LLM execution loop and progress display."""

import random
import time
import json
from typing import TYPE_CHECKING, Optional, Any

from swecli.repl.constants.thinking_verbs import THINKING_VERBS
from swecli.ui_textual.utils.tool_display import format_tool_call
from swecli.core.runtime import OperationMode

if TYPE_CHECKING:
    from rich.console import Console
    from swecli.core.runtime import ModeManager, ConfigManager
    from swecli.core.context_engineering.history import SessionManager, UndoManager
    from swecli.core.runtime.approval import ApprovalManager
    from swecli.ui_textual.formatters_internal.output_formatter import OutputFormatter


class ExecutionManager:
    """Handles LLM execution and tool execution."""

    MAX_ERROR_RECOVERY_ATTEMPTS = 3

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
        self._current_task_monitor: Optional[Any] = None

    def request_interrupt(self) -> bool:
        """Request interrupt of currently running task.

        Returns:
            True if interrupt was requested, False otherwise
        """
        if self._current_task_monitor is not None:
            self._current_task_monitor.request_interrupt()
            return True
        return False

    def call_llm_with_progress(self, agent, messages, task_monitor) -> tuple:
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
    ) -> tuple:
        """Execute a single tool call.

        Args:
            tool_call: Tool call specification
            tool_registry: Tool registry
            approval_manager: Approval manager
            undo_manager: Undo manager
            ui_callback: Optional UI callback for nested tool call display

        Returns:
            Tuple of (result, operation_summary, error)
        """
        from swecli.core.runtime.monitoring import TaskMonitor
        from swecli.ui_textual.components.task_progress import TaskProgressDisplay

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
            operation_summary = tool_call_display
            error = None if result.get("success") else result.get("error", "Tool execution failed")

            # Stop progress if it was started
            if tool_progress:
                tool_progress.stop()

            # Display result (skip for spawn_subagent since it shows separate_response)
            if not result.get("separate_response"):
                panel = self.output_formatter.format_tool_result(tool_name, tool_args, result)
                self.console.print(panel)

            return result, operation_summary, error
        finally:
            # Clear current monitor
            self._current_task_monitor = None

    def should_nudge_agent(self, consecutive_reads: int, messages: list) -> bool:
        """Check if agent should be nudged to conclude.

        Args:
            consecutive_reads: Number of consecutive read operations
            messages: Message history

        Returns:
            True if nudge was added
        """
        if consecutive_reads >= 5:
            # Silently nudge the agent without displaying a message
            messages.append({
                "role": "user",
                "content": "Based on what you've seen, please summarize your findings and explain what needs to be done next."
            })
            return True
        return False

    def should_attempt_error_recovery(self, messages: list, attempts: int) -> bool:
        """Check if we should inject a recovery prompt after tool failure.

        Args:
            messages: Message history
            attempts: Number of recovery attempts already made

        Returns:
            True if recovery should be attempted
        """
        if attempts >= self.MAX_ERROR_RECOVERY_ATTEMPTS:
            return False

        # Find the most recent tool result
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                # Check if the tool failed
                if content.startswith("Error:"):
                    return True
                # Only check the most recent tool result
                break
        return False
