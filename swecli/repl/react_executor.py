"""ReAct loop execution with SOLID principles."""

import json
from typing import TYPE_CHECKING, Optional

from swecli.models.message import ChatMessage, Role, ToolCall as ToolCallModel
from swecli.core.runtime.monitoring import TaskMonitor
from swecli.core.utils.tool_result_summarizer import summarize_tool_result
from swecli.ui_textual.utils.tool_display import format_tool_call

if TYPE_CHECKING:
    from rich.console import Console
    from swecli.core.runtime import ModeManager
    from swecli.core.context_engineering.history import SessionManager
    from swecli.core.runtime.approval import ApprovalManager
    from swecli.core.context_engineering.history import UndoManager
    from swecli.models.config import Config


class DeepAgentConfigurator:
    """Handles Deep Agent setup and configuration."""

    def __init__(self, console: "Console", mode_manager: "ModeManager", session_manager: "SessionManager"):
        """Initialize Deep Agent configurator.

        Args:
            console: Rich console for output
            mode_manager: Mode manager
            session_manager: Session manager
        """
        self.console = console
        self.mode_manager = mode_manager
        self.session_manager = session_manager

    def configure_agent(
        self,
        agent,
        ui_callback,
        approval_manager: "ApprovalManager",
        undo_manager: "UndoManager",
        skip_if_approval_active: bool = True,
    ):
        """Configure Deep Agent with managers and UI callback.

        Args:
            agent: Agent to configure
            ui_callback: UI callback for real-time updates (can be None)
            approval_manager: Approval manager
            undo_manager: Undo manager
            skip_if_approval_active: Skip configuration if approval panel is active
        """
        # Check if approval panel is currently active
        approval_active = False
        if skip_if_approval_active and ui_callback:
            if hasattr(ui_callback, 'app') and hasattr(ui_callback.app, '_approval_prompt_controller'):
                approval_active = ui_callback.app._approval_prompt_controller.active

        # Debug: Approval state check
        if ui_callback and hasattr(ui_callback, 'on_debug'):
            ui_callback.on_debug(f"Approval panel active: {approval_active}", "AGENT")

        # Only update Deep Agent if approval is not active
        if not approval_active:
            # Debug: Deep Agent integration starting
            if ui_callback and hasattr(ui_callback, 'on_debug'):
                agent_type = type(agent).__name__
                ui_callback.on_debug(f"Configuring Deep Agent integration ({agent_type})", "AGENT")

            # Connect UI callback to Deep Agent for tool transparency
            if ui_callback and hasattr(agent, 'set_ui_callback'):
                agent.set_ui_callback(ui_callback)
                if hasattr(ui_callback, 'on_debug'):
                    ui_callback.on_debug("UI callback connected to Deep Agent", "AGENT")

            # Update managers on Deep Agent's backend
            if hasattr(agent, 'update_managers'):
                agent.update_managers(
                    mode_manager=self.mode_manager,
                    approval_manager=approval_manager,
                    undo_manager=undo_manager,
                    task_monitor=None,  # Will be created per-iteration
                    session_manager=self.session_manager
                )
                if ui_callback and hasattr(ui_callback, 'on_debug'):
                    ui_callback.on_debug("Managers updated on Deep Agent backend", "AGENT")
        else:
            # Debug: Skipping Deep Agent setup due to active approval
            if ui_callback and hasattr(ui_callback, 'on_debug'):
                ui_callback.on_debug("Skipping Deep Agent setup (approval active)", "AGENT")


class MessagePersister:
    """Handles message persistence to session."""

    def __init__(self, session_manager: "SessionManager", config: "Config"):
        """Initialize message persister.

        Args:
            session_manager: Session manager
            config: Configuration
        """
        self.session_manager = session_manager
        self.config = config

    def persist_assistant_message(
        self,
        content: str,
        raw_content: Optional[str] = None,
        tool_calls: Optional[list] = None,
    ):
        """Persist assistant message to session.

        Args:
            content: Message content
            raw_content: Raw LLM content (optional)
            tool_calls: Tool call objects (optional)
        """
        metadata = {}
        if raw_content is not None:
            metadata["raw_content"] = raw_content

        assistant_msg = ChatMessage(
            role=Role.ASSISTANT,
            content=content,
            metadata=metadata,
            tool_calls=tool_calls or None,
        )
        self.session_manager.add_message(assistant_msg, self.config.auto_save_interval)

    def build_tool_call_objects(self, tool_calls: list, messages: list) -> list:
        """Build ToolCall objects from tool call dicts and results.

        Args:
            tool_calls: List of tool call dictionaries
            messages: Message history with tool results

        Returns:
            List of ToolCallModel objects
        """
        tool_call_objects = []
        for tc in tool_calls:
            tool_result = None
            tool_error = None

            # Find corresponding result in messages
            for msg in reversed(messages):
                if msg.get("role") == "tool" and msg.get("tool_call_id") == tc["id"]:
                    content = msg.get("content", "")
                    if content.startswith("Error:"):
                        tool_error = content[6:].strip()
                    else:
                        tool_result = content
                    break

            # Generate concise summary for LLM context
            tool_name = tc["function"]["name"]
            result_summary = summarize_tool_result(tool_name, tool_result, tool_error)

            tool_call_objects.append(
                ToolCallModel(
                    id=tc["id"],
                    name=tool_name,
                    parameters=json.loads(tc["function"]["arguments"]),
                    result=tool_result,
                    result_summary=result_summary,
                    error=tool_error,
                    approved=True,
                )
            )

        return tool_call_objects


class ReActExecutor:
    """Executes ReAct loop (Reasoning → Acting → Observing)."""

    READ_OPERATIONS = {"read_file", "list_files", "search_code"}

    def __init__(
        self,
        console: "Console",
        session_manager: "SessionManager",
        config: "Config",
        mode_manager: "ModeManager",
        llm_caller,
        tool_executor,
        react_controller,
        message_printer_callback,
    ):
        """Initialize ReAct executor.

        Args:
            console: Rich console
            session_manager: Session manager
            config: Configuration
            mode_manager: Mode manager
            llm_caller: LLM caller instance
            tool_executor: Tool executor instance
            react_controller: ReAct controller instance
            message_printer_callback: Callback to print markdown messages
        """
        self.console = console
        self.session_manager = session_manager
        self.config = config
        self.mode_manager = mode_manager
        self.llm_caller = llm_caller
        self.tool_executor = tool_executor
        self.react_controller = react_controller
        self._print_markdown_message = message_printer_callback

        self.agent_configurator = DeepAgentConfigurator(console, mode_manager, session_manager)
        self.message_persister = MessagePersister(session_manager, config)

        # State tracking
        self._last_latency_ms = None
        self._last_error = None
        self._last_operation_summary = "—"

    def execute_react_loop(
        self,
        messages: list,
        agent,
        tool_registry,
        approval_manager: "ApprovalManager",
        undo_manager: "UndoManager",
        query: str,
        ui_callback=None,
    ) -> tuple:
        """Execute the full ReAct loop.

        Args:
            messages: Message history
            agent: Agent to use
            tool_registry: Tool registry
            approval_manager: Approval manager
            undo_manager: Undo manager
            query: Original user query
            ui_callback: UI callback for real-time updates (None for non-callback mode)

        Returns:
            Tuple of (last_operation_summary, last_error, last_latency_ms)
        """
        # Configure Deep Agent
        self.agent_configurator.configure_agent(
            agent, ui_callback, approval_manager, undo_manager
        )

        # Debug: Entering ReAct loop
        if ui_callback and hasattr(ui_callback, 'on_debug'):
            ui_callback.on_debug("Entering ReAct loop (Reasoning → Acting → Observing)", "REACT")

        try:
            # Notify UI that thinking is starting (callback mode only)
            if ui_callback and hasattr(ui_callback, 'on_thinking_start'):
                ui_callback.on_thinking_start()

            consecutive_reads = 0
            iteration = 0

            while True:
                iteration += 1

                # Debug: ReAct iteration
                if ui_callback and hasattr(ui_callback, 'on_debug'):
                    ui_callback.on_debug(f"ReAct iteration #{iteration}", "REACT")

                # Execute single iteration
                should_break, operation_cancelled = self._execute_iteration(
                    messages, agent, tool_registry, approval_manager,
                    undo_manager, query, ui_callback, consecutive_reads
                )

                if should_break:
                    break

                if operation_cancelled:
                    break

                # Update consecutive reads counter
                consecutive_reads = self._update_consecutive_reads(messages, consecutive_reads)

                # Check if agent needs nudge
                if self.react_controller.should_nudge_agent(consecutive_reads, messages):
                    consecutive_reads = 0

        except Exception as e:
            self.console.print(f"[red]Error: {str(e)}[/red]")
            import traceback
            traceback.print_exc()
            self._last_error = str(e)

        return (self._last_operation_summary, self._last_error, self._last_latency_ms)

    def _execute_iteration(
        self,
        messages: list,
        agent,
        tool_registry,
        approval_manager,
        undo_manager,
        query: str,
        ui_callback,
        consecutive_reads: int,
    ) -> tuple:
        """Execute a single ReAct iteration.

        Returns:
            Tuple of (should_break, operation_cancelled)
        """
        # Call LLM
        response, latency_ms = self._call_llm(agent, messages, ui_callback)
        self._last_latency_ms = latency_ms

        # Handle LLM errors
        if not response["success"]:
            self._handle_llm_error(response, ui_callback)
            return (True, False)  # Break loop

        # Notify UI that thinking is complete
        if ui_callback and hasattr(ui_callback, 'on_thinking_complete'):
            ui_callback.on_thinking_complete()

        # Extract response data
        message_payload = response.get("message", {}) or {}
        raw_llm_content = message_payload.get("content")
        llm_description = response.get("content", raw_llm_content or "")
        if raw_llm_content is None:
            raw_llm_content = llm_description

        tool_calls = response.get("tool_calls")
        if tool_calls is None:
            tool_calls = message_payload.get("tool_calls")

        normalized_description = (llm_description or "").strip()

        # If no tool calls, task is complete
        if not tool_calls:
            self._handle_completion(normalized_description, raw_llm_content, ui_callback)
            return (True, False)  # Break loop

        # Display assistant's thinking (callback mode only)
        if ui_callback and llm_description and hasattr(ui_callback, 'on_assistant_message'):
            ui_callback.on_assistant_message(llm_description)

        # Add assistant message to history
        messages.append({
            "role": "assistant",
            "content": raw_llm_content,
            "tool_calls": tool_calls,
        })

        # Execute tool calls
        operation_cancelled = self._execute_tool_calls(
            tool_calls, messages, tool_registry, approval_manager,
            undo_manager, ui_callback
        )

        # Persist assistant message with tool calls
        tool_call_objects = self.message_persister.build_tool_call_objects(tool_calls, messages)
        self.message_persister.persist_assistant_message(
            normalized_description or "",
            raw_llm_content,
            tool_call_objects,
        )

        # Record learnings
        if tool_call_objects:
            outcome = "error" if any(tc.error for tc in tool_call_objects) else "success"
            self.tool_executor.set_last_agent_response(normalized_description or "")
            self.tool_executor.record_tool_learnings(query, tool_call_objects, outcome, agent)

        return (False, operation_cancelled)

    def _call_llm(self, agent, messages: list, ui_callback) -> tuple:
        """Call LLM with progress display.

        Returns:
            Tuple of (response, latency_ms)
        """
        # Debug: Calling LLM
        if ui_callback and hasattr(ui_callback, 'on_debug'):
            from swecli.repl.query_enhancer import QueryEnhancer
            messages_summary = QueryEnhancer.format_messages_summary(messages)
            ui_callback.on_debug(f"Calling LLM: {messages_summary}", "LLM")

        task_monitor = TaskMonitor()
        response, latency_ms = self.llm_caller.call_llm_with_progress(agent, messages, task_monitor)

        # Debug: LLM response received
        if ui_callback and hasattr(ui_callback, 'on_debug'):
            success = response.get("success", False)
            ui_callback.on_debug(f"LLM response received (success={success}, latency={latency_ms}ms)", "LLM")

        return response, latency_ms

    def _handle_llm_error(self, response: dict, ui_callback):
        """Handle LLM call error.

        Args:
            response: LLM response with error
            ui_callback: UI callback (can be None)
        """
        error_text = response.get("error", "Unknown error")

        # Check if this is an interruption
        if "interrupted" in error_text.lower():
            self._last_error = error_text
            if ui_callback and hasattr(ui_callback, 'on_interrupt'):
                ui_callback.on_interrupt()
            else:
                # Non-callback mode
                self.console.print(f"  ⎿  [bold red]Interrupted · What should I do instead?[/bold red]")
            # Don't save to session
        else:
            self.console.print(f"[red]Error: {error_text}[/red]")
            fallback = ChatMessage(role=Role.ASSISTANT, content=f"❌ {error_text}")
            self._last_error = error_text
            self.session_manager.add_message(fallback, self.config.auto_save_interval)

            if ui_callback and hasattr(ui_callback, 'on_assistant_message'):
                ui_callback.on_assistant_message(fallback.content)

    def _handle_completion(self, description: str, raw_content: str, ui_callback):
        """Handle task completion (no tool calls).

        Args:
            description: Assistant's description
            raw_content: Raw LLM content
            ui_callback: UI callback (can be None)
        """
        if not description:
            description = "Warning: model returned no reply."

        if ui_callback and hasattr(ui_callback, 'on_assistant_message'):
            ui_callback.on_assistant_message(description)
        else:
            # Non-callback mode
            self.console.print(f"\n[dim]{description}[/dim]")

        self.message_persister.persist_assistant_message(description, raw_content)

    def _execute_tool_calls(
        self,
        tool_calls: list,
        messages: list,
        tool_registry,
        approval_manager,
        undo_manager,
        ui_callback,
    ) -> bool:
        """Execute all tool calls and add results to messages.

        Args:
            tool_calls: List of tool calls to execute
            messages: Message history to append results to
            tool_registry: Tool registry
            approval_manager: Approval manager
            undo_manager: Undo manager
            ui_callback: UI callback (can be None)

        Returns:
            True if operation was cancelled, False otherwise
        """
        operation_cancelled = False

        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            tool_args = tool_call["function"]["arguments"]

            # Notify UI about tool call (callback mode)
            if ui_callback and hasattr(ui_callback, 'on_tool_call'):
                ui_callback.on_tool_call(tool_name, tool_args)

            # Debug: Executing tool
            if ui_callback and hasattr(ui_callback, 'on_debug'):
                ui_callback.on_debug(f"Executing tool: {tool_name}", "TOOL")

            # Non-callback mode: Display tool call immediately
            if not ui_callback:
                tool_args_dict = json.loads(tool_args)
                tool_call_display = format_tool_call(tool_name, tool_args_dict)
                self.console.print(f"\n⏺ [cyan]{tool_call_display}[/cyan]")

            # Execute tool
            result = self.tool_executor.execute_tool_call(
                tool_call, tool_registry, approval_manager, undo_manager
            )

            # Update state
            tool_args_dict = json.loads(tool_args)
            tool_call_display = format_tool_call(tool_name, tool_args_dict)
            self._last_operation_summary = tool_call_display

            if result.get("success"):
                self._last_error = None
            else:
                self._last_error = result.get("error", "Tool execution failed")

            # Debug: Tool execution completed
            if ui_callback and hasattr(ui_callback, 'on_debug'):
                success = result.get("success", False)
                ui_callback.on_debug(f"Tool '{tool_name}' completed (success={success})", "TOOL")

            # Check if operation was cancelled/interrupted
            if result.get("interrupted"):
                operation_cancelled = True

            # Notify UI about tool result (callback mode)
            if ui_callback and hasattr(ui_callback, 'on_tool_result'):
                ui_callback.on_tool_result(tool_name, tool_args, result)

            # Handle separate_response for spawn_subagent (display as assistant message)
            separate_response = result.get("separate_response")
            if separate_response and ui_callback:
                if hasattr(ui_callback, 'on_assistant_message'):
                    ui_callback.on_assistant_message(separate_response)

            # Add tool result to messages (use separate_response for spawn_subagent if available)
            if result["success"]:
                tool_result = separate_response if separate_response else result.get("output", "")
            else:
                tool_result = f"Error: {result.get('error', 'Tool execution failed')}"
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": tool_result,
            })

        return operation_cancelled

    def _update_consecutive_reads(self, messages: list, current_count: int) -> int:
        """Update consecutive reads counter based on last tool calls.

        Args:
            messages: Message history
            current_count: Current consecutive reads count

        Returns:
            Updated consecutive reads count
        """
        # Find last assistant message with tool calls
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                tool_calls = msg["tool_calls"]
                all_reads = all(tc["function"]["name"] in self.READ_OPERATIONS for tc in tool_calls)
                return current_count + 1 if all_reads else 0

        return current_count
