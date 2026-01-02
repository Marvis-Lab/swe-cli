"""Execution manager for LLM calls and tool execution."""

from typing import TYPE_CHECKING, Tuple, Optional, Any, Dict
import random
import time
import json
from rich.console import Console

from swecli.repl.constants import THINKING_VERBS
from swecli.ui_textual.components.task_progress import TaskProgressDisplay
from swecli.core.runtime.monitoring import TaskMonitor
from swecli.core.runtime import OperationMode
from swecli.ui_textual.utils.tool_display import format_tool_call

if TYPE_CHECKING:
    from swecli.core.runtime import ModeManager
    from swecli.ui_textual.formatters_internal.output_formatter import OutputFormatter
    from swecli.core.context_engineering.history import SessionManager

class ExecutionManager:
    """Manages LLM interaction and tool execution."""

    def __init__(
        self,
        console: Console,
        mode_manager: "ModeManager",
        output_formatter: "OutputFormatter",
        session_manager: "SessionManager",
    ):
        """Initialize execution manager.

        Args:
            console: Rich console
            mode_manager: Mode manager
            output_formatter: Output formatter
            session_manager: Session manager
        """
        self.console = console
        self.mode_manager = mode_manager
        self.output_formatter = output_formatter
        self.session_manager = session_manager

        # Track current monitor for interrupt support
        self._current_task_monitor: Optional[TaskMonitor] = None
        self._last_operation_summary = "—"
        self._last_error = None

    @property
    def current_task_monitor(self) -> Optional[TaskMonitor]:
        return self._current_task_monitor

    @property
    def last_operation_summary(self) -> str:
        return self._last_operation_summary

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def call_llm_with_progress(self, agent, messages) -> Tuple[Dict, int]:
        """Call LLM with progress display.

        Args:
            agent: Agent to use
            messages: Message history

        Returns:
            Tuple of (response, latency_ms)
        """
        task_monitor = TaskMonitor()

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
        approval_manager,
        undo_manager,
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
        tool_progress = None
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
