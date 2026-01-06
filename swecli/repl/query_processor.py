"""Query processing for REPL."""

import json
import os
import random
from datetime import datetime
from typing import TYPE_CHECKING, Iterable

from swecli.core.context_engineering.memory import (
    Playbook,
    AgentResponse,
    Reflector,
    Curator,
    ReflectorOutput,
    CuratorOutput,
)
from swecli.ui_textual.utils.tool_display import format_tool_call

if TYPE_CHECKING:
    from rich.console import Console
    from swecli.core.runtime import ModeManager
    from swecli.core.context_engineering.history import SessionManager
    from swecli.core.runtime.approval import ApprovalManager
    from swecli.core.context_engineering.history import UndoManager
    from swecli.core.context_engineering.tools.implementations import FileOperations
    from swecli.ui_textual.formatters_internal.output_formatter import OutputFormatter
    from swecli.ui_textual.components import StatusLine
    from swecli.models.config import Config
    from swecli.core.runtime import ConfigManager
    from swecli.models.message import ToolCall


class QueryProcessor:
    """Processes user queries using ReAct pattern.
    
    This class orchestrates query processing by coordinating:
    - Query enhancement (@ file references)
    - Message preparation with playbook context
    - LLM calls with progress display
    - Tool execution with approval/undo
    - ACE learning from tool execution results
    
    Note:
        THINKING_VERBS constant has been consolidated into LLMCaller.
        This class is being incrementally refactored to compose 
        specialized components (LLMCaller, QueryEnhancer, ToolExecutor).
    """

    REFLECTION_WINDOW_SIZE = 10
    MAX_PLAYBOOK_STRATEGIES = 30
    PLAYBOOK_DEBUG_PATH = "/tmp/swecli_debug/playbook_evolution.log"

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
        self.file_ops = file_ops
        self.output_formatter = output_formatter
        self.status_line = status_line
        self._print_markdown_message = message_printer_callback

        # UI state trackers
        self._last_latency_ms = None
        self._last_operation_summary = "—"
        self._last_error = None
        self._notification_center = None

        # Interrupt support - track current task monitor
        self._current_task_monitor: Optional[Any] = None

        # ACE Components - Initialize on first use (lazy loading)
        self._ace_reflector: Optional[Reflector] = None
        self._ace_curator: Optional[Curator] = None
        self._last_agent_response: Optional[AgentResponse] = None
        self._execution_count = 0

        # Composed components (SOLID refactoring)
        from swecli.repl.query_enhancer import QueryEnhancer
        self._query_enhancer = QueryEnhancer(
            file_ops=file_ops,
            session_manager=session_manager,
            config=config,
            console=console,
        )

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
        if self._current_task_monitor is not None:
            self._current_task_monitor.request_interrupt()
            return True
        return False

    def _init_ace_components(self, agent):
        """Initialize ACE components lazily on first use.

        Args:
            agent: Agent with LLM client
        """
        if self._ace_reflector is None:
            # Initialize ACE roles with native implementation
            # The native components use swecli's LLM client directly
            self._ace_reflector = Reflector(agent.client)

            self._ace_curator = Curator(agent.client)

    def enhance_query(self, query: str) -> str:
        """Enhance query with file contents if referenced.
        
        Delegates to QueryEnhancer.

        Args:
            query: Original query

        Returns:
            Enhanced query with file contents or @ references stripped
        """
        return self._query_enhancer.enhance_query(query)

    def _prepare_messages(self, query: str, enhanced_query: str, agent) -> list:
        """Prepare messages for LLM API call.
        
        Delegates to QueryEnhancer.

        Args:
            query: Original query
            enhanced_query: Query with file contents or @ references processed
            agent: Agent with system prompt

        Returns:
            List of API messages
        """
        return self._query_enhancer.prepare_messages(query, enhanced_query, agent)

    def _call_llm_with_progress(self, agent, messages, task_monitor) -> tuple:
        """Call LLM with progress display.

        Args:
            agent: Agent to use
            messages: Message history
            task_monitor: Task monitor for tracking

        Returns:
            Tuple of (response, latency_ms)
        """
        from swecli.ui_textual.components.task_progress import TaskProgressDisplay
        import time

        # Get random thinking verb from consolidated LLMCaller
        from swecli.repl.llm_caller import LLMCaller
        thinking_verb = random.choice(LLMCaller.THINKING_VERBS)
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

    def _record_tool_learnings(
        self,
        query: str,
        tool_call_objects: Iterable["ToolCall"],
        outcome: str,
        agent,
    ) -> None:
        """Use ACE Reflector and Curator to evolve playbook from tool execution.

        This implements the full ACE workflow:
        1. Reflector analyzes what happened (LLM-powered)
        2. Curator decides playbook changes (delta operations)
        3. Apply deltas to evolve playbook

        Args:
            query: User's query
            tool_call_objects: Tool calls that were executed
            outcome: "success", "error", or "partial"
            agent: Agent with LLM client (for ACE initialization)
        """
        session = self.session_manager.current_session
        if not session:
            return

        tool_calls = list(tool_call_objects)
        if not tool_calls:
            return

        # Skip if no agent response (ACE workflow needs it)
        if not self._last_agent_response:
            return

        try:
            # Initialize ACE components if needed
            self._init_ace_components(agent)

            playbook = session.get_playbook()

            # Format tool feedback for reflector
            feedback = self._format_tool_feedback(tool_calls, outcome)

            # STEP 1: Reflect on execution using ACE Reflector
            reflection = self._ace_reflector.reflect(
                question=query,
                agent_response=self._last_agent_response,
                playbook=playbook,
                ground_truth=None,
                feedback=feedback
            )

            # STEP 2: Apply bullet tags from reflection
            for bullet_tag in reflection.bullet_tags:
                try:
                    playbook.tag_bullet(bullet_tag.id, bullet_tag.tag)
                except (ValueError, KeyError):
                    continue

            # STEP 3: Curate playbook updates using ACE Curator
            self._execution_count += 1
            curator_output = self._ace_curator.curate(
                reflection=reflection,
                playbook=playbook,
                question_context=query,
                progress=f"Query #{self._execution_count}"
            )

            # STEP 4: Apply delta operations
            bullets_before = len(playbook.bullets())
            playbook.apply_delta(curator_output.delta)
            bullets_after = len(playbook.bullets())

            # Save updated playbook
            session.update_playbook(playbook)

            # Debug logging
            if bullets_after != bullets_before or curator_output.delta.operations:
                debug_dir = os.path.dirname(self.PLAYBOOK_DEBUG_PATH)
                os.makedirs(debug_dir, exist_ok=True)
                with open(self.PLAYBOOK_DEBUG_PATH, "a", encoding="utf-8") as log:
                    timestamp = datetime.now().isoformat()
                    log.write(f"\n{'=' * 60}\n")
                    log.write(f"🧠 ACE PLAYBOOK EVOLUTION - {timestamp}\n")
                    log.write(f"{'=' * 60}\n")
                    log.write(f"Query: {query}\n")
                    log.write(f"Outcome: {outcome}\n")
                    log.write(f"Bullets: {bullets_before} -> {bullets_after}\n")
                    log.write(f"Delta Operations: {len(curator_output.delta.operations)}\n")
                    for op in curator_output.delta.operations:
                        log.write(f"  - {op.type}: {op.section} - {op.content[:80] if op.content else op.bullet_id}\n")
                    log.write(f"Reflection Key Insight: {reflection.key_insight}\n")
                    log.write(f"Curator Reasoning: {curator_output.delta.reasoning[:200]}\n")

        except Exception as e:  # pragma: no cover
            # Log error but don't break query processing
            import traceback
            debug_dir = os.path.dirname(self.PLAYBOOK_DEBUG_PATH)
            os.makedirs(debug_dir, exist_ok=True)
            with open(self.PLAYBOOK_DEBUG_PATH, "a", encoding="utf-8") as log:
                log.write(f"\n{'!' * 60}\n")
                log.write(f"❌ ACE ERROR: {str(e)}\n")
                log.write(traceback.format_exc())

    def _format_tool_feedback(self, tool_calls: list, outcome: str) -> str:
        """Format tool execution results as feedback string for ACE Reflector.

        Args:
            tool_calls: List of ToolCall objects with results
            outcome: "success", "error", or "partial"

        Returns:
            Formatted feedback string
        """
        lines = [f"Outcome: {outcome}"]
        lines.append(f"Tools executed: {len(tool_calls)}")

        if outcome == "success":
            lines.append("All tools completed successfully")
            # Add brief summary of what was done
            tool_names = [tc.name for tc in tool_calls]
            lines.append(f"Tools: {', '.join(tool_names)}")
        elif outcome == "error":
            # List errors
            errors = [f"{tc.name}: {tc.error}" for tc in tool_calls if tc.error]
            lines.append(f"Errors ({len(errors)}):")
            for error in errors[:3]:  # First 3 errors
                lines.append(f"  - {error[:200]}")
        else:  # partial
            successes = sum(1 for tc in tool_calls if not tc.error)
            lines.append(f"Partial success: {successes}/{len(tool_calls)} tools succeeded")

        return "\n".join(lines)

    def _execute_tool_call(
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
        from swecli.core.runtime.monitoring import TaskMonitor
        from swecli.ui_textual.components.task_progress import TaskProgressDisplay
        from swecli.core.runtime import OperationMode
        import json

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

    def _should_nudge_agent(self, consecutive_reads: int, messages: list) -> bool:
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
        enhanced_query = self.enhance_query(query)

        # Prepare messages for API
        messages = self._prepare_messages(query, enhanced_query, agent)

        try:
            # ReAct loop: Reasoning → Acting → Observing
            consecutive_reads = 0
            iteration = 0
            consecutive_no_tool_calls = 0
            MAX_NUDGE_ATTEMPTS = 3  # After this many nudges, treat as implicit completion
            READ_OPERATIONS = {"read_file", "list_files", "search_code"}

            while True:
                iteration += 1

                # Call LLM
                task_monitor = TaskMonitor()
                response, latency_ms = self._call_llm_with_progress(agent, messages, task_monitor)
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
                self._last_agent_response = AgentResponse(
                    content=normalized_description,
                    tool_calls=tool_calls or []
                )

                # If no tool calls, check if we should nudge or accept implicit completion
                if not has_tool_calls:
                    # Check if last tool execution failed (should nudge to retry)
                    last_tool_failed = False
                    for msg in reversed(messages):
                        if msg.get("role") == "tool":
                            content = msg.get("content", "")
                            if content.startswith("Error:"):
                                last_tool_failed = True
                            break

                    if last_tool_failed:
                        # Last tool failed - nudge agent to fix and retry
                        consecutive_no_tool_calls += 1

                        if consecutive_no_tool_calls >= MAX_NUDGE_ATTEMPTS:
                            # Exhausted nudge attempts - give up
                            if not normalized_description:
                                normalized_description = "Warning: could not complete after multiple attempts."
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

                        # Nudge agent to fix the error and retry
                        if normalized_description:
                            messages.append({
                                "role": "assistant",
                                "content": raw_llm_content or normalized_description,
                            })
                        messages.append({
                            "role": "user",
                            "content": "The previous operation failed. Please fix the issue and try again, or call task_complete with status='failed' if you cannot proceed.",
                        })
                        continue

                    # Last tool succeeded (or no previous tool) - accept implicit completion
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

                # Reset counter when we have tool calls
                consecutive_no_tool_calls = 0

                # Add assistant message with tool calls to history
                messages.append({
                    "role": "assistant",
                    "content": raw_llm_content,
                    "tool_calls": tool_calls,
                })

                # Track read-only operations
                all_reads = all(tc["function"]["name"] in READ_OPERATIONS for tc in tool_calls)
                consecutive_reads = consecutive_reads + 1 if all_reads else 0

                # Check for explicit task completion
                for tool_call in tool_calls:
                    if tool_call["function"]["name"] == "task_complete":
                        import json as json_mod
                        args = json_mod.loads(tool_call["function"]["arguments"])
                        summary = args.get("summary", "Task completed")
                        self.console.print(f"\n[dim]{summary}[/dim]")
                        metadata = {}
                        if raw_llm_content is not None:
                            metadata["raw_content"] = raw_llm_content
                        assistant_msg = ChatMessage(
                            role=Role.ASSISTANT,
                            content=summary,
                            metadata=metadata,
                        )
                        self.session_manager.add_message(assistant_msg, self.config.auto_save_interval)
                        break

                # Check if task_complete was called (break out of main loop)
                if any(tc["function"]["name"] == "task_complete" for tc in tool_calls):
                    break

                # Execute tool calls
                for tool_call in tool_calls:
                    result = self._execute_tool_call(tool_call, tool_registry, approval_manager, undo_manager)

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
                    self._record_tool_learnings(query, tool_call_objects, outcome, agent)

                # Check if agent needs nudge
                if self._should_nudge_agent(consecutive_reads, messages):
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

        # Debug: Show session state after adding user message
        if ui_callback and hasattr(ui_callback, 'on_debug'):
            session = self.session_manager.current_session
            if session:
                msg_count = len(session.messages)
                ui_callback.on_debug(f"Session has {msg_count} messages after adding user msg", "SESSION")
                last_3 = session.messages[-3:] if msg_count >= 3 else session.messages
                for i, msg in enumerate(last_3):
                    content = (msg.content[:50] if msg.content else '(empty)').replace('\n', ' ')
                    has_tools = bool(getattr(msg, 'tool_calls', None))
                    ui_callback.on_debug(f"  [{msg_count - len(last_3) + i}] {msg.role.value}: {content}... (tools={has_tools})", "SESSION")

        # Enhance query with file contents
        enhanced_query = self.enhance_query(query)

        # Prepare messages for API
        messages = self._prepare_messages(query, enhanced_query, agent)

        # Debug: Show messages being sent to LLM
        if ui_callback and hasattr(ui_callback, 'on_debug'):
            ui_callback.on_debug(f"Sending {len(messages)} messages to LLM:", "LLM_MESSAGES")
            for i, msg in enumerate(messages):
                role = msg.get('role', 'unknown')
                content = str(msg.get('content', '') or '')[:80].replace('\n', ' ')
                has_tools = 'tool_calls' in msg
                ui_callback.on_debug(f"  [{i}] {role}: {content}... (tools={has_tools})", "LLM_MESSAGES")

        try:
            # ReAct loop: Reasoning → Acting → Observing
            consecutive_reads = 0
            iteration = 0
            consecutive_no_tool_calls = 0
            MAX_NUDGE_ATTEMPTS = 3  # After this many nudges, treat as implicit completion
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
                response, latency_ms = self._call_llm_with_progress(agent, messages, task_monitor)
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

                # If no tool calls, check if we should nudge or accept implicit completion
                if not has_tool_calls:
                    # Check if last tool execution failed (should nudge to retry)
                    last_tool_failed = False
                    for msg in reversed(messages):
                        if msg.get("role") == "tool":
                            content = msg.get("content", "")
                            if content.startswith("Error:"):
                                last_tool_failed = True
                            break

                    if last_tool_failed:
                        # Last tool failed - nudge agent to fix and retry
                        consecutive_no_tool_calls += 1

                        if consecutive_no_tool_calls >= MAX_NUDGE_ATTEMPTS:
                            # Exhausted nudge attempts - give up
                            if not normalized_description:
                                normalized_description = "Warning: could not complete after multiple attempts."
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

                        # Nudge agent to fix the error and retry
                        if normalized_description and ui_callback and hasattr(ui_callback, 'on_assistant_message'):
                            ui_callback.on_assistant_message(normalized_description)
                        if normalized_description:
                            messages.append({
                                "role": "assistant",
                                "content": raw_llm_content or normalized_description,
                            })
                        messages.append({
                            "role": "user",
                            "content": "The previous operation failed. Please fix the issue and try again, or call task_complete with status='failed' if you cannot proceed.",
                        })
                        continue

                    # Last tool succeeded (or no previous tool) - accept implicit completion
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

                # Reset counter when we have tool calls
                consecutive_no_tool_calls = 0

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

                # Check for explicit task completion
                for tool_call in tool_calls:
                    if tool_call["function"]["name"] == "task_complete":
                        import json as json_mod
                        args = json_mod.loads(tool_call["function"]["arguments"])
                        summary = args.get("summary", "Task completed")
                        if ui_callback and hasattr(ui_callback, 'on_assistant_message'):
                            ui_callback.on_assistant_message(summary)
                        metadata = {}
                        if raw_llm_content is not None:
                            metadata["raw_content"] = raw_llm_content
                        assistant_msg = ChatMessage(
                            role=Role.ASSISTANT,
                            content=summary,
                            metadata=metadata,
                        )
                        self.session_manager.add_message(assistant_msg, self.config.auto_save_interval)
                        break

                # Check if task_complete was called (break out of main loop)
                if any(tc["function"]["name"] == "task_complete" for tc in tool_calls):
                    break

                # Execute tool calls with real-time display
                operation_cancelled = False
                tool_results_by_id = {}  # Capture full result dicts for session storage
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
                    result = self._execute_tool_call(
                        tool_call,
                        tool_registry,
                        approval_manager,
                        undo_manager,
                        ui_callback=ui_callback,
                    )

                    # Store full result dict for session persistence (before it's converted to string)
                    tool_results_by_id[tool_call["id"]] = result

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
                    tool_name = tc["function"]["name"]

                    # Get full result dict (stored during execution) for history restoration
                    # This preserves stdout, stderr, diff, success, etc. for proper display
                    full_result = tool_results_by_id.get(tc["id"], {})

                    # Extract error from result dict
                    tool_error = full_result.get("error") if not full_result.get("success", True) else None

                    # For LLM summary, use the string output
                    tool_result_str = full_result.get("output", "") if full_result.get("success", True) else None

                    # Generate concise summary for LLM context
                    result_summary = summarize_tool_result(tool_name, tool_result_str, tool_error)

                    # Get nested tool calls from ui_callback for spawn_subagent
                    nested_calls = []
                    if tool_name == "spawn_subagent" and ui_callback and hasattr(ui_callback, 'get_and_clear_nested_calls'):
                        nested_calls = ui_callback.get_and_clear_nested_calls()

                    tool_call_objects.append(
                        ToolCallModel(
                            id=tc["id"],
                            name=tool_name,
                            parameters=json.loads(tc["function"]["arguments"]),
                            result=full_result,  # Store FULL dict, not string
                            result_summary=result_summary,
                            error=tool_error,
                            approved=True,
                            nested_tool_calls=nested_calls,
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
                    self._record_tool_learnings(query, tool_call_objects, outcome, agent)

                # Nudge agent if too many consecutive reads
                if self._should_nudge_agent(consecutive_reads, messages):
                    consecutive_reads = 0

            # Update status line
            self._render_status_line()

        except Exception as e:
            self.console.print(f"[red]Error: {str(e)}[/red]")
            import traceback
            traceback.print_exc()
            self._last_error = str(e)

        return (self._last_operation_summary, self._last_error, self._last_latency_ms)
