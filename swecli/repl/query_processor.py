"""Query processing for REPL."""

import json
from typing import TYPE_CHECKING, Optional

from swecli.repl.processors import ACEProcessor, ContextPreparer, ExecutionManager

if TYPE_CHECKING:
    from rich.console import Console
    from swecli.core.runtime import ModeManager, ConfigManager
    from swecli.core.context_engineering.history import SessionManager, UndoManager
    from swecli.core.runtime.approval import ApprovalManager
    from swecli.core.context_engineering.tools.implementations import FileOperations
    from swecli.ui_textual.formatters_internal.output_formatter import OutputFormatter
    from swecli.ui_textual.components import StatusLine
    from swecli.models.config import Config


class QueryProcessor:
    """Processes user queries using ReAct pattern."""

    def __init__(
        self,
        console: "Console",
        session_manager: "SessionManager",
        config: "Config",
        config_manager: "ConfigManager",
        mode_manager: "ModeManager",
        file_ops: "FileOperations",
        output_formatter: "OutputFormatter",
        status_line: "StatusLine",
        message_printer_callback,
    ):
        """Initialize query processor.

        Args:
            console: Rich console for output
            session_manager: Session manager for message tracking
            config: Configuration
            config_manager: Configuration manager
            mode_manager: Mode manager for current mode
            file_ops: File operations for query enhancement
            output_formatter: Output formatter for tool results
            status_line: Status line renderer
            message_printer_callback: Callback to print markdown messages
        """
        self.console = console
        self.session_manager = session_manager
        self.config = config
        self.config_manager = config_manager
        self.mode_manager = mode_manager
        self.status_line = status_line
        self._print_markdown_message = message_printer_callback

        # Initialize processors
        self.ace_processor = ACEProcessor(session_manager)
        self.context_preparer = ContextPreparer(console, session_manager, file_ops, config)
        self.execution_manager = ExecutionManager(console, session_manager, mode_manager, output_formatter)

        # UI state trackers
        self._last_latency_ms = None
        self._last_operation_summary = "—"
        self._last_error = None
        self._notification_center = None

    def set_notification_center(self, notification_center):
        """Set notification center for status line rendering.

        Args:
            notification_center: Notification center instance
        """
        self._notification_center = notification_center

    def request_interrupt(self) -> bool:
        """Request interrupt of currently running task (LLM call or tool execution).

        Returns:
            True if interrupt was requested, False if no task is running
        """
        return self.execution_manager.request_interrupt()

    def _render_status_line(self):
        """Render the status line with current context."""
        total_tokens = self.session_manager.current_session.total_tokens() if self.session_manager.current_session else 0
        self.status_line.render(
            model=self.config.model,
            working_dir=self.config_manager.working_dir,
            tokens_used=total_tokens,
            tokens_limit=self.config.max_context_tokens,
            mode=self.mode_manager.current_mode.value.upper(),
            latency_ms=self._last_latency_ms,
            key_hints=[
                ("Esc S", "Status detail"),
                ("Esc C", "Context"),
                ("Esc N", "Notifications"),
                ("/help", "Commands"),
            ],
            notifications=[note.summary() for note in self._notification_center.latest(2)] if self._notification_center and self._notification_center.has_items() else None,
        )

    def process_query(
        self,
        query: str,
        agent,
        tool_registry,
        approval_manager: "ApprovalManager",
        undo_manager: "UndoManager",
    ) -> tuple:
        """Process a user query with AI using ReAct pattern.

        Args:
            query: User query
            agent: Agent to use for LLM calls
            tool_registry: Tool registry for executing tools
            approval_manager: Approval manager for user confirmations
            undo_manager: Undo manager for operation history

        Returns:
            Tuple of (last_operation_summary, last_error, last_latency_ms)
        """
        from swecli.models.message import ChatMessage, Role
        from swecli.core.runtime.monitoring import TaskMonitor

        # Add user message to session
        user_msg = ChatMessage(role=Role.USER, content=query)
        self.session_manager.add_message(user_msg, self.config.auto_save_interval)

        # Enhance query with file contents
        enhanced_query = self.context_preparer.enhance_query(query)

        # Prepare messages for API
        messages = self.context_preparer.prepare_messages(query, enhanced_query, agent)

        try:
            # ReAct loop: Reasoning → Acting → Observing
            consecutive_reads = 0
            iteration = 0
            error_recovery_attempts = 0
            READ_OPERATIONS = {"read_file", "list_files", "search_code"}

            while True:
                iteration += 1

                # Call LLM
                task_monitor = TaskMonitor()
                response, latency_ms = self.execution_manager.call_llm_with_progress(agent, messages, task_monitor)
                self._last_latency_ms = latency_ms

                if not response["success"]:
                    error_text = response.get("error", "Unknown error")
                    # Check if this is an interruption
                    if "interrupted" in error_text.lower():
                        # For interruptions, just print directly (no UI callback in non-callback mode)
                        self.console.print(f"  ⎿  [bold red]Interrupted · What should I do instead?[/bold red]")
                        self._last_error = error_text
                        # Don't save to session
                    else:
                        self.console.print(f"[red]Error: {error_text}[/red]")
                        fallback = ChatMessage(role=Role.ASSISTANT, content=f"❌ {error_text}")
                        self._last_error = error_text
                        self.session_manager.add_message(fallback, self.config.auto_save_interval)
                    break

                # Get LLM description and tool calls
                message_payload = response.get("message", {}) or {}
                raw_llm_content = message_payload.get("content")
                llm_description = response.get("content", raw_llm_content or "")
                if raw_llm_content is None:
                    raw_llm_content = llm_description

                tool_calls = response.get("tool_calls")
                if tool_calls is None:
                    tool_calls = message_payload.get("tool_calls")
                has_tool_calls = bool(tool_calls)
                normalized_description = (llm_description or "").strip()

                # Store agent response for ACE learning
                self.ace_processor.set_last_agent_response(
                    content=normalized_description,
                    tool_calls=tool_calls or []
                )

                # If no tool calls, check if we should attempt error recovery
                if not has_tool_calls:
                    # Check if last tool failed and we should try to recover
                    if self.execution_manager.should_attempt_error_recovery(messages, error_recovery_attempts):
                        # Add assistant's suggestion to history
                        if normalized_description:
                            messages.append({
                                "role": "assistant",
                                "content": raw_llm_content or normalized_description,
                            })
                        # Inject recovery prompt
                        messages.append({
                            "role": "user",
                            "content": "The previous command failed. Please fix the issue and try again.",
                        })
                        error_recovery_attempts += 1
                        continue  # Loop back to LLM

                    # No recovery needed - task is complete
                    if not normalized_description:
                        normalized_description = "Warning: model returned no reply."
                    self.console.print(f"\n[dim]{normalized_description}[/dim]")
                    metadata = {}
                    if raw_llm_content is not None:
                        metadata["raw_content"] = raw_llm_content
                    assistant_msg = ChatMessage(
                        role=Role.ASSISTANT,
                        content=normalized_description,
                        metadata=metadata,
                    )
                    self.session_manager.add_message(assistant_msg, self.config.auto_save_interval)
                    break

                # Add assistant message with tool calls to history
                messages.append({
                    "role": "assistant",
                    "content": raw_llm_content,
                    "tool_calls": tool_calls,
                })

                # Track read-only operations
                all_reads = all(tc["function"]["name"] in READ_OPERATIONS for tc in tool_calls)
                consecutive_reads = consecutive_reads + 1 if all_reads else 0

                # Execute tool calls
                for tool_call in tool_calls:
                    result, summary, error = self.execution_manager.execute_tool_call(
                        tool_call, tool_registry, approval_manager, undo_manager
                    )
                    self._last_operation_summary = summary
                    if error:
                        self._last_error = error
                    else:
                        self._last_error = None

                    # Add tool result to messages
                    tool_result = result.get("output", "") if result["success"] else f"Error: {result.get('error', 'Tool execution failed')}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_result,
                    })

                # Persist assistant step with tool calls to session
                from swecli.models.message import ToolCall as ToolCallModel
                from swecli.core.utils.tool_result_summarizer import summarize_tool_result

                tool_call_objects = []
                for tc in tool_calls:
                    tool_result = None
                    tool_error = None
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

                if normalized_description or tool_call_objects:
                    metadata = {}
                    if raw_llm_content is not None:
                        metadata["raw_content"] = raw_llm_content

                    assistant_msg = ChatMessage(
                        role=Role.ASSISTANT,
                        content=normalized_description or "",
                        metadata=metadata,
                        tool_calls=tool_call_objects,
                    )
                    self.session_manager.add_message(assistant_msg, self.config.auto_save_interval)

                if tool_call_objects:
                    outcome = "error" if any(tc.error for tc in tool_call_objects) else "success"
                    self.ace_processor.record_tool_learnings(query, tool_call_objects, outcome, agent)

                # Check if agent needs nudge
                if self.execution_manager.should_nudge_agent(consecutive_reads, messages):
                    consecutive_reads = 0

            # Show status line
            self._render_status_line()

        except Exception as e:
            self.console.print(f"[red]Error: {str(e)}[/red]")
            import traceback
            traceback.print_exc()
            self._last_error = str(e)

        return (self._last_operation_summary, self._last_error, self._last_latency_ms)

    def process_query_with_callback(
        self,
        query: str,
        agent,
        tool_registry,
        approval_manager: "ApprovalManager",
        undo_manager: "UndoManager",
        ui_callback,
    ) -> tuple:
        """Process a user query with AI using ReAct pattern with UI callback for real-time updates.

        Args:
            query: User query
            agent: Agent to use for LLM calls
            tool_registry: Tool registry for executing tools
            approval_manager: Approval manager for user confirmations
            undo_manager: Undo manager for operation history
            ui_callback: UI callback for real-time tool display

        Returns:
            Tuple of (last_operation_summary, last_error, last_latency_ms)
        """
        from swecli.models.message import ChatMessage, Role
        from swecli.core.runtime.monitoring import TaskMonitor

        # Notify UI that thinking is starting
        if ui_callback and hasattr(ui_callback, 'on_thinking_start'):
            ui_callback.on_thinking_start()

        # Debug: Query processing started
        if ui_callback and hasattr(ui_callback, 'on_debug'):
            ui_callback.on_debug(f"Processing query: {query[:50]}{'...' if len(query) > 50 else ''}", "QUERY")

        # Add user message to session
        user_msg = ChatMessage(role=Role.USER, content=query)
        self.session_manager.add_message(user_msg, self.config.auto_save_interval)

        # Enhance query with file contents
        enhanced_query = self.context_preparer.enhance_query(query)

        # Prepare messages for API
        messages = self.context_preparer.prepare_messages(query, enhanced_query, agent)

        try:
            # ReAct loop: Reasoning → Acting → Observing
            consecutive_reads = 0
            iteration = 0
            error_recovery_attempts = 0
            READ_OPERATIONS = {"read_file", "list_files", "search_code"}

            while True:
                iteration += 1

                # Debug: ReAct iteration
                if ui_callback and hasattr(ui_callback, 'on_debug'):
                    ui_callback.on_debug(f"ReAct iteration #{iteration}", "REACT")

                # Debug: Calling LLM
                if ui_callback and hasattr(ui_callback, 'on_debug'):
                    ui_callback.on_debug(f"Calling LLM with {len(messages)} messages", "LLM")

                # Call LLM
                task_monitor = TaskMonitor()
                response, latency_ms = self.execution_manager.call_llm_with_progress(agent, messages, task_monitor)
                self._last_latency_ms = latency_ms

                # Debug: LLM response
                if ui_callback and hasattr(ui_callback, 'on_debug'):
                    success = response.get("success", False)
                    ui_callback.on_debug(f"LLM response (success={success}, latency={latency_ms}ms)", "LLM")

                if not response["success"]:
                    error_text = response.get("error", "Unknown error")
                    # Check if this is an interruption
                    if "interrupted" in error_text.lower():
                        # Display interrupt using UI callback - same mechanism as tool results
                        self._last_error = error_text
                        if ui_callback and hasattr(ui_callback, 'on_interrupt'):
                            ui_callback.on_interrupt()
                        # Don't save to session
                    else:
                        self.console.print(f"[red]Error: {error_text}[/red]")
                        fallback = ChatMessage(role=Role.ASSISTANT, content=f"❌ {error_text}")
                        self._last_error = error_text
                        self.session_manager.add_message(fallback, self.config.auto_save_interval)
                        if ui_callback and hasattr(ui_callback, 'on_assistant_message'):
                            ui_callback.on_assistant_message(fallback.content)
                    break

                # Get LLM description and tool calls
                message_payload = response.get("message", {}) or {}
                raw_llm_content = message_payload.get("content")
                llm_description = response.get("content", raw_llm_content or "")
                if raw_llm_content is None:
                    raw_llm_content = llm_description

                tool_calls = response.get("tool_calls")
                if tool_calls is None:
                    tool_calls = message_payload.get("tool_calls")
                has_tool_calls = bool(tool_calls)
                normalized_description = (llm_description or "").strip()

                # Notify UI that thinking is complete
                if ui_callback and hasattr(ui_callback, 'on_thinking_complete'):
                    ui_callback.on_thinking_complete()

                # If no tool calls, check if we should attempt error recovery
                if not has_tool_calls:
                    # Check if last tool failed and we should try to recover
                    if self.execution_manager.should_attempt_error_recovery(messages, error_recovery_attempts):
                        # Show assistant's suggestion via UI callback
                        if normalized_description and ui_callback and hasattr(ui_callback, 'on_assistant_message'):
                            ui_callback.on_assistant_message(normalized_description)
                        # Add assistant's suggestion to history
                        if normalized_description:
                            messages.append({
                                "role": "assistant",
                                "content": raw_llm_content or normalized_description,
                            })
                        # Inject recovery prompt
                        messages.append({
                            "role": "user",
                            "content": "The previous command failed. Please fix the issue and try again.",
                        })
                        error_recovery_attempts += 1
                        continue  # Loop back to LLM

                    # No recovery needed - task is complete
                    if not normalized_description:
                        normalized_description = "Warning: model returned no reply."
                    if ui_callback and hasattr(ui_callback, 'on_assistant_message'):
                        ui_callback.on_assistant_message(normalized_description)
                    metadata = {}
                    if raw_llm_content is not None:
                        metadata["raw_content"] = raw_llm_content
                    assistant_msg = ChatMessage(
                        role=Role.ASSISTANT,
                        content=normalized_description,
                        metadata=metadata,
                    )
                    self.session_manager.add_message(assistant_msg, self.config.auto_save_interval)
                    break

                # Display assistant's thinking text BEFORE tool execution
                if llm_description and ui_callback and hasattr(ui_callback, 'on_assistant_message'):
                    ui_callback.on_assistant_message(llm_description)

                # Add assistant message with tool calls to history
                messages.append({
                    "role": "assistant",
                    "content": raw_llm_content,
                    "tool_calls": tool_calls,
                })

                # Track read-only operations
                all_reads = all(tc["function"]["name"] in READ_OPERATIONS for tc in tool_calls)
                consecutive_reads = consecutive_reads + 1 if all_reads else 0

                # Execute tool calls with real-time display
                operation_cancelled = False
                for tool_call in tool_calls:
                    tool_name = tool_call["function"]["name"]

                    # Debug: Executing tool
                    if ui_callback and hasattr(ui_callback, 'on_debug'):
                        ui_callback.on_debug(f"Executing tool: {tool_name}", "TOOL")

                    # Notify UI about tool call
                    if ui_callback and hasattr(ui_callback, 'on_tool_call'):
                        ui_callback.on_tool_call(
                            tool_name,
                            tool_call["function"]["arguments"]
                        )

                    # Pass ui_callback to tool execution for nested subagent display
                    result, summary, error = self.execution_manager.execute_tool_call(
                        tool_call,
                        tool_registry,
                        approval_manager,
                        undo_manager,
                        ui_callback=ui_callback,
                    )
                    self._last_operation_summary = summary
                    if error:
                        self._last_error = error
                    else:
                        self._last_error = None

                    # Debug: Tool result
                    if ui_callback and hasattr(ui_callback, 'on_debug'):
                        success = result.get("success", False)
                        ui_callback.on_debug(f"Tool '{tool_name}' completed (success={success})", "TOOL")

                    # Check if operation was cancelled/interrupted
                    if result.get("interrupted"):
                        operation_cancelled = True

                    # Notify UI about tool result
                    if ui_callback and hasattr(ui_callback, 'on_tool_result'):
                        ui_callback.on_tool_result(
                            tool_call["function"]["name"],
                            tool_call["function"]["arguments"],
                            result
                        )

                    # Handle separate_response for spawn_subagent (display as assistant message)
                    separate_response = result.get("separate_response")
                    if separate_response and ui_callback:
                        # Display the final result as an assistant message
                        if hasattr(ui_callback, 'on_assistant_message'):
                            ui_callback.on_assistant_message(separate_response)

                    # Add tool result to messages (use separate_response for spawn_subagent)
                    if result["success"]:
                        tool_result = separate_response if separate_response else result.get("output", "")
                    else:
                        tool_result = f"Error: {result.get('error', 'Tool execution failed')}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_result,
                    })

                # If operation was cancelled, exit loop immediately without calling LLM
                if operation_cancelled:
                    break

                # Persist assistant step with tool calls to session
                from swecli.models.message import ToolCall as ToolCallModel
                from swecli.core.utils.tool_result_summarizer import summarize_tool_result

                tool_call_objects = []
                for tc in tool_calls:
                    tool_result = None
                    tool_error = None
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

                assistant_msg = ChatMessage(
                    role=Role.ASSISTANT,
                    content=normalized_description or "",
                    metadata={"raw_content": raw_llm_content} if raw_llm_content is not None else {},
                    tool_calls=tool_call_objects,
                )
                self.session_manager.add_message(assistant_msg, self.config.auto_save_interval)

                if tool_call_objects:
                    outcome = "error" if any(tc.error for tc in tool_call_objects) else "success"
                    self.ace_processor.record_tool_learnings(query, tool_call_objects, outcome, agent)

                # Nudge agent if too many consecutive reads
                if self.execution_manager.should_nudge_agent(consecutive_reads, messages):
                    consecutive_reads = 0

            # Update status line
            self._render_status_line()

        except Exception as e:
            self.console.print(f"[red]Error: {str(e)}[/red]")
            import traceback
            traceback.print_exc()
            self._last_error = str(e)

        return (self._last_operation_summary, self._last_error, self._last_latency_ms)
