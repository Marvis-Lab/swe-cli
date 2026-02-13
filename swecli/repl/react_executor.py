"""ReAct loop executor."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional, Dict, Any

# Maximum number of tools to execute in parallel
MAX_CONCURRENT_TOOLS = 5

# Dual memory architecture constants
SHORT_TERM_PAIRS = 3  # Number of recent message pairs to include in short-term memory
MAX_TOOL_RESULT_LEN = 300  # Truncate tool results in short-term memory

from swecli.models.message import ChatMessage, Role, ToolCall as ToolCallModel
from swecli.core.context_engineering.memory import AgentResponse
from swecli.core.context_engineering.memory.conversation_summarizer import ConversationSummarizer
from swecli.core.runtime.monitoring import TaskMonitor
from swecli.ui_textual.utils.tool_display import format_tool_call
from swecli.ui_textual.components.task_progress import TaskProgressDisplay
from swecli.core.utils.tool_result_summarizer import summarize_tool_result
from swecli.core.agents.prompts import get_injection

logger = logging.getLogger(__name__)


def _debug_log(message: str) -> None:
    """Write debug message to /tmp/swecli_react_debug.log."""
    from datetime import datetime

    log_file = "/tmp/swecli_react_debug.log"
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def _session_debug() -> "SessionDebugLogger":
    """Get the current session debug logger."""
    from swecli.core.debug import get_debug_logger

    return get_debug_logger()


if TYPE_CHECKING:
    from rich.console import Console
    from swecli.core.context_engineering.history import SessionManager
    from swecli.models.config import Config
    from swecli.repl.llm_caller import LLMCaller
    from swecli.repl.tool_executor import ToolExecutor
    from swecli.core.runtime.approval import ApprovalManager
    from swecli.core.context_engineering.history import UndoManager
    from swecli.core.debug.session_debug_logger import SessionDebugLogger


class LoopAction(Enum):
    """Action to take after an iteration."""

    CONTINUE = auto()
    BREAK = auto()


@dataclass
class IterationContext:
    """Context for a single ReAct iteration."""

    query: str
    messages: list
    agent: Any
    tool_registry: Any
    approval_manager: "ApprovalManager"
    undo_manager: "UndoManager"
    ui_callback: Optional[Any]
    iteration_count: int = 0
    consecutive_reads: int = 0
    consecutive_no_tool_calls: int = 0
    continue_after_subagent: bool = False  # If True, don't inject stop signal after subagent


class ReactExecutor:
    """Executes ReAct loop (Reasoning → Acting → Observing)."""

    READ_OPERATIONS = {"read_file", "list_files", "search"}
    MAX_NUDGE_ATTEMPTS = 3

    def __init__(
        self,
        console: "Console",
        session_manager: "SessionManager",
        config: "Config",
        llm_caller: "LLMCaller",
        tool_executor: "ToolExecutor",
    ):
        """Initialize ReAct executor."""
        self.console = console
        self.session_manager = session_manager
        self.config = config
        self._llm_caller = llm_caller
        self._tool_executor = tool_executor
        self._last_operation_summary = None
        self._last_error = None
        self._last_latency_ms = 0
        self._last_thinking_error: Optional[dict[str, Any]] = None

        # Tracking variables for current iteration (for session persistence)
        self._current_thinking_trace: Optional[str] = None
        self._current_reasoning_content: Optional[str] = None
        self._current_token_usage: Optional[dict] = None

        # Track current task monitor for interrupt support (thinking phase uses this)
        self._current_task_monitor: Optional[TaskMonitor] = None

        # Auto-compaction support
        self._compactor = None
        self._force_compact_next = False  # Set by /compact command

        self._conversation_summarizer = ConversationSummarizer(
            regenerate_threshold=5,  # Regenerate summary after 5 new messages
        )
        # Load cached state from session if available
        if self.session_manager.current_session:
            cache_data = self.session_manager.current_session.metadata.get("conversation_summary")
            if cache_data:
                self._conversation_summarizer.load_from_dict(cache_data)

    def request_interrupt(self) -> bool:
        """Request interrupt of currently running task (thinking or tool execution).

        Returns:
            True if interrupt was requested, False if no task is running
        """
        from swecli.ui_textual.debug_logger import debug_log

        debug_log("ReactExecutor", "request_interrupt called")
        debug_log("ReactExecutor", f"_current_task_monitor={self._current_task_monitor}")

        if self._current_task_monitor is not None:
            self._current_task_monitor.request_interrupt()
            debug_log("ReactExecutor", "Called task_monitor.request_interrupt()")
            return True
        debug_log("ReactExecutor", "No active task monitor")
        return False

    def execute(
        self,
        query: str,
        messages: list,
        agent,
        tool_registry,
        approval_manager: "ApprovalManager",
        undo_manager: "UndoManager",
        ui_callback=None,
        continue_after_subagent: bool = False,
    ) -> tuple:
        """Execute ReAct loop."""

        # Initialize context
        ctx = IterationContext(
            query=query,
            messages=messages,
            agent=agent,
            tool_registry=tool_registry,
            approval_manager=approval_manager,
            undo_manager=undo_manager,
            ui_callback=ui_callback,
            continue_after_subagent=continue_after_subagent,
        )

        # Notify UI start
        if ui_callback and hasattr(ui_callback, "on_thinking_start"):
            ui_callback.on_thinking_start()

        # Debug: Query processing started
        if ui_callback and hasattr(ui_callback, "on_debug"):
            ui_callback.on_debug(
                f"Processing query: {query[:50]}{'...' if len(query) > 50 else ''}", "QUERY"
            )

        try:
            while True:
                ctx.iteration_count += 1
                _session_debug().log(
                    "react_iteration_start",
                    "react",
                    iteration=ctx.iteration_count,
                    query_preview=query[:200],
                    message_count=len(messages),
                )
                action = self._run_iteration(ctx)
                _session_debug().log(
                    "react_iteration_end",
                    "react",
                    iteration=ctx.iteration_count,
                    action=action.name.lower(),
                )
                if action == LoopAction.BREAK:
                    break
        except Exception as e:
            self.console.print(f"[red]Error: {str(e)}[/red]")
            import traceback

            tb = traceback.format_exc()
            traceback.print_exc()
            self._last_error = str(e)
            _session_debug().log(
                "error", "react", error=str(e), traceback=tb
            )

        return (self._last_operation_summary, self._last_error, self._last_latency_ms)

    def _get_thinking_trace(
        self,
        messages: list,
        agent,
        ui_callback=None,
    ) -> Optional[str]:
        """Make a SEPARATE LLM call to get thinking trace.

        Uses dual memory architecture:
        - Episodic memory: LLM-summarized conversation history
        - Short-term memory: Last N message pairs in full detail

        Args:
            messages: Current conversation messages
            agent: The agent to use for the thinking call
            ui_callback: Optional UI callback for displaying thinking

        Returns:
            Thinking trace string, or None on failure
        """
        try:
            # Build thinking-specific system prompt template
            thinking_system_prompt_template = agent.build_system_prompt(thinking_visible=True)

            # === BUILD DUAL MEMORY CONTEXT ===
            context_parts = []

            # Count non-system messages
            non_system_count = len([m for m in messages if m.get("role") != "system"])

            # 1. EPISODIC MEMORY: Get/generate conversation summary (only if enough history)
            if non_system_count > SHORT_TERM_PAIRS * 3:
                if self._conversation_summarizer.needs_regeneration(non_system_count):
                    summary = self._conversation_summarizer.generate_summary(
                        messages, agent.call_thinking_llm
                    )
                else:
                    summary = self._conversation_summarizer.get_cached_summary()

                if summary:
                    context_parts.append(get_injection("episodic_memory_header", summary=summary))

            # 2. SHORT-TERM MEMORY: Extract last N message pairs
            short_term = self._extract_short_term_memory(messages, SHORT_TERM_PAIRS)
            if short_term:
                context_parts.append(
                    get_injection("short_term_memory_header", short_term=short_term)
                )

            formatted_context = "\n".join(context_parts)

            # Inject context into system prompt
            thinking_system_prompt = thinking_system_prompt_template.replace(
                "{context}", formatted_context
            )

            # Build minimal message list - just system prompt + empty user message
            thinking_messages = [
                {"role": "system", "content": thinking_system_prompt},
                {
                    "role": "user",
                    "content": get_injection("thinking_analysis_prompt"),
                },
            ]

            # Call LLM WITHOUT tools - just get reasoning
            task_monitor = TaskMonitor()
            # Track task monitor for interrupt support
            self._current_task_monitor = task_monitor
            from swecli.ui_textual.debug_logger import debug_log

            debug_log("ReactExecutor", f"Thinking phase: SET _current_task_monitor={task_monitor}")
            try:
                response = agent.call_thinking_llm(thinking_messages, task_monitor)

                if response.get("success"):
                    thinking_trace = response.get("content", "")

                    # Display in UI
                    if thinking_trace and ui_callback and hasattr(ui_callback, "on_thinking"):
                        ui_callback.on_thinking(thinking_trace)

                    return thinking_trace
                else:
                    # Log the error for debugging
                    error = response.get("error", "Unknown error")
                    if ui_callback and hasattr(ui_callback, "on_debug"):
                        ui_callback.on_debug(f"Thinking phase error: {error}", "THINK")
                    # Store full response for interrupt checking (reused by _handle_llm_error)
                    self._last_thinking_error = response
            finally:
                # Clear task monitor after thinking phase
                self._current_task_monitor = None
                debug_log("ReactExecutor", "Thinking phase: CLEARED _current_task_monitor")

        except Exception as e:
            # Log exceptions for debugging
            if ui_callback and hasattr(ui_callback, "on_debug"):
                ui_callback.on_debug(f"Thinking phase exception: {str(e)}", "THINK")
            import logging

            logging.getLogger(__name__).exception("Error in thinking phase")

        return None

    def _critique_and_refine_thinking(
        self,
        thinking_trace: str,
        messages: list,
        agent,
        ui_callback=None,
    ) -> str:
        """Critique thinking trace and optionally refine it.

        When self-critique mode is enabled, this method:
        1. Calls the critique LLM to analyze the thinking trace
        2. Uses the critique to generate a refined thinking trace

        Args:
            thinking_trace: The original thinking trace to critique
            messages: Current conversation messages (for context in refinement)
            agent: The agent to use for critique/refinement calls
            ui_callback: Optional UI callback for displaying critique

        Returns:
            Refined thinking trace (or original if critique fails)
        """
        from swecli.core.runtime.monitoring import TaskMonitor

        try:
            # Step 1: Get critique of the thinking trace
            task_monitor = TaskMonitor()
            self._current_task_monitor = task_monitor

            try:
                critique_response = agent.call_critique_llm(thinking_trace, task_monitor)

                if not critique_response.get("success"):
                    error = critique_response.get("error", "Unknown error")
                    if ui_callback and hasattr(ui_callback, "on_debug"):
                        ui_callback.on_debug(f"Critique phase error: {error}", "CRITIQUE")
                    return thinking_trace  # Return original on failure

                critique = critique_response.get("content", "")

                if not critique or not critique.strip():
                    return thinking_trace  # No critique generated

                # Display critique in UI if callback available
                if ui_callback and hasattr(ui_callback, "on_critique"):
                    ui_callback.on_critique(critique)

                # Step 2: Refine thinking trace using the critique
                refined_trace = self._refine_thinking_with_critique(
                    thinking_trace, critique, messages, agent, ui_callback
                )

                return refined_trace if refined_trace else thinking_trace

            finally:
                self._current_task_monitor = None

        except Exception as e:
            if ui_callback and hasattr(ui_callback, "on_debug"):
                ui_callback.on_debug(f"Critique phase exception: {str(e)}", "CRITIQUE")
            import logging
            logging.getLogger(__name__).exception("Error in critique phase")
            return thinking_trace  # Return original on exception

    def _refine_thinking_with_critique(
        self,
        thinking_trace: str,
        critique: str,
        messages: list,
        agent,
        ui_callback=None,
    ) -> Optional[str]:
        """Generate a refined thinking trace incorporating critique feedback.

        Args:
            thinking_trace: Original thinking trace
            critique: Critique feedback
            messages: Current conversation messages
            agent: Agent for LLM call
            ui_callback: Optional UI callback

        Returns:
            Refined thinking trace, or None on failure
        """
        from swecli.core.runtime.monitoring import TaskMonitor

        try:
            # Build refinement prompt
            refinement_system = agent.build_system_prompt(thinking_visible=True)

            # Build context similar to thinking phase but with critique included
            context_parts = []

            # Add short-term memory
            short_term = self._extract_short_term_memory(messages, SHORT_TERM_PAIRS)
            if short_term:
                context_parts.append(
                    get_injection("short_term_memory_header", short_term=short_term)
                )

            formatted_context = "\n".join(context_parts)
            refinement_system = refinement_system.replace("{context}", formatted_context)

            refinement_messages = [
                {"role": "system", "content": refinement_system},
                {
                    "role": "user",
                    "content": f"""Your previous reasoning was:

{thinking_trace}

A critique identified these issues:

{critique}

Please provide refined reasoning that addresses these concerns. Keep it concise (under 100 words).""",
                },
            ]

            task_monitor = TaskMonitor()
            self._current_task_monitor = task_monitor

            try:
                response = agent.call_thinking_llm(refinement_messages, task_monitor)

                if response.get("success"):
                    refined = response.get("content", "")
                    if refined and refined.strip():
                        # Display refined thinking in UI
                        if ui_callback and hasattr(ui_callback, "on_thinking"):
                            ui_callback.on_thinking(f"[Refined]\n{refined}")
                        return refined
            finally:
                self._current_task_monitor = None

        except Exception as e:
            if ui_callback and hasattr(ui_callback, "on_debug"):
                ui_callback.on_debug(f"Refinement error: {str(e)}", "CRITIQUE")

        return None

    def _extract_short_term_memory(self, messages: list, n_pairs: int) -> str:
        """Extract the last N message pairs (user->assistant->tools) in full detail.

        A "pair" is defined as:
        - User message
        - Assistant response (with tool calls)
        - Tool results (if any)

        Args:
            messages: Full message list
            n_pairs: Number of pairs to extract

        Returns:
            Formatted string of recent exchanges
        """
        # Filter out system messages
        non_system = [m for m in messages if m.get("role") != "system"]

        if not non_system:
            return ""

        # Find user message boundaries to identify "pairs"
        pair_starts = []
        for i, msg in enumerate(non_system):
            if msg.get("role") == "user":
                pair_starts.append(i)

        # Get last N pair starting indices
        recent_pair_starts = pair_starts[-n_pairs:] if len(pair_starts) >= n_pairs else pair_starts

        if not recent_pair_starts:
            return ""

        # Extract messages from first recent pair to end
        start_idx = recent_pair_starts[0]
        recent_messages = non_system[start_idx:]

        # Format with truncation
        parts = []
        for msg in recent_messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "user":
                parts.append(f"USER:\n{content}\n")
            elif role == "assistant":
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    tool_names = [tc["function"]["name"] for tc in tool_calls]
                    parts.append(f"ASSISTANT CALLED: {', '.join(tool_names)}\n")
                if content:
                    parts.append(f"ASSISTANT:\n{content[:500]}\n")
            elif role == "tool":
                # Truncate tool results more aggressively
                tool_content = content[:MAX_TOOL_RESULT_LEN]
                if len(content) > MAX_TOOL_RESULT_LEN:
                    tool_content += f"... ({len(content)} chars total)"
                parts.append(f"TOOL RESULT:\n{tool_content}\n")

        return "\n".join(parts)

    def _check_subagent_completion(self, messages: list) -> bool:
        """Check if the last tool result was from a completed subagent.

        Returns True if the last tool result indicates subagent completion.
        Used to skip thinking phase AND inject stop signal.
        """
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                is_subagent_complete = (
                    "[completion_status=success]" in content or "[SYNC COMPLETE]" in content
                )
                _debug_log(f"[SUBAGENT_CHECK] is_subagent={is_subagent_complete}")
                return is_subagent_complete
            # Stop searching if we hit a user message (new turn)
            if msg.get("role") == "user" and "<thinking_trace>" not in msg.get("content", ""):
                return False
        return False

    def _maybe_compact(self, ctx: IterationContext) -> None:
        """Auto-compact messages if approaching the context window limit."""
        if self._compactor is None:
            from swecli.core.context_engineering.compaction import ContextCompactor

            self._compactor = ContextCompactor(self.config, ctx.agent._http_client)

        system_prompt = ctx.agent.system_prompt
        should = self._force_compact_next or self._compactor.should_compact(
            ctx.messages, system_prompt
        )

        if should:
            self._force_compact_next = False
            before_count = len(ctx.messages)
            compacted = self._compactor.compact(ctx.messages, system_prompt)
            ctx.messages[:] = compacted  # Mutate in-place
            after_count = len(ctx.messages)
            logger.info("Compacted %d messages → %d", before_count, after_count)
            if ctx.ui_callback and hasattr(ctx.ui_callback, "on_message"):
                ctx.ui_callback.on_message(
                    f"Context auto-compacted ({before_count} → {after_count} messages)"
                )

    def _run_iteration(self, ctx: IterationContext) -> LoopAction:
        """Run a single ReAct iteration."""

        # Debug logging
        if ctx.ui_callback and hasattr(ctx.ui_callback, "on_debug"):
            ctx.ui_callback.on_debug(f"Calling LLM with {len(ctx.messages)} messages", "LLM")

        # Get thinking visibility from tool registry
        thinking_visible = False
        if ctx.tool_registry and hasattr(ctx.tool_registry, "thinking_handler"):
            thinking_visible = ctx.tool_registry.thinking_handler.is_visible

        # Check if last tool was subagent completion
        subagent_just_completed = self._check_subagent_completion(ctx.messages)

        # Log decision point to file
        _debug_log(
            f"[ITERATION] thinking_visible={thinking_visible}, "
            f"subagent_completed={subagent_just_completed}, "
            f"msg_count={len(ctx.messages)}"
        )

        # THINKING PHASE: Get thinking trace BEFORE action (when thinking mode is ON)
        # Skip thinking phase after subagent completion - main agent decides directly
        if thinking_visible and not subagent_just_completed:
            thinking_trace = self._get_thinking_trace(ctx.messages, ctx.agent, ctx.ui_callback)

            # Check for interrupt from thinking phase (reuse existing _handle_llm_error)
            if self._last_thinking_error is not None:
                error_response = self._last_thinking_error
                self._last_thinking_error = None  # Clear the stored error
                error_text = error_response.get("error", "")
                if "interrupted" in error_text.lower():
                    # Use existing error handler - it calls on_interrupt() and returns BREAK
                    return self._handle_llm_error(error_response, ctx)

            # SELF-CRITIQUE PHASE: Critique and refine thinking trace (when level is Self-Critique)
            includes_critique = False
            if ctx.tool_registry and hasattr(ctx.tool_registry, "thinking_handler"):
                includes_critique = ctx.tool_registry.thinking_handler.includes_critique

            if includes_critique and thinking_trace:
                thinking_trace = self._critique_and_refine_thinking(
                    thinking_trace, ctx.messages, ctx.agent, ctx.ui_callback
                )

            self._current_thinking_trace = thinking_trace  # Track for persistence
            if thinking_trace:
                # Inject trace as user message for the action phase
                ctx.messages.append(
                    {
                        "role": "user",
                        "content": get_injection(
                            "thinking_trace_injection", thinking_trace=thinking_trace
                        ),
                    }
                )

        # STOP SIGNAL: After subagent completion, tell agent to just summarize
        # Skip if continue_after_subagent is True (e.g., /init needs to continue)
        if subagent_just_completed and not ctx.continue_after_subagent:
            _debug_log("[ITERATION] Injecting stop signal after subagent completion")
            ctx.messages.append(
                {
                    "role": "user",
                    "content": get_injection("subagent_complete_signal"),
                }
            )

        # AUTO-COMPACTION: Compact messages if approaching context limit
        self._maybe_compact(ctx)

        # ACTION PHASE: Call LLM with tools (no force_think)
        task_monitor = TaskMonitor()
        from swecli.ui_textual.debug_logger import debug_log

        debug_log(
            "ReactExecutor",
            f"Calling call_llm_with_progress, _llm_caller={id(self._llm_caller)}, task_monitor={task_monitor}",
        )
        _session_debug().log(
            "llm_call_start",
            "llm",
            model=getattr(ctx.agent, "model", "unknown"),
            message_count=len(ctx.messages),
            thinking_visible=thinking_visible,
        )
        response, latency_ms = self._llm_caller.call_llm_with_progress(
            ctx.agent, ctx.messages, task_monitor, thinking_visible=thinking_visible
        )
        debug_log(
            "ReactExecutor", f"call_llm_with_progress returned, success={response.get('success')}"
        )
        self._last_latency_ms = latency_ms
        _session_debug().log(
            "llm_call_end",
            "llm",
            duration_ms=latency_ms,
            success=response.get("success", False),
            tokens=response.get("usage"),
            has_tool_calls=bool(response.get("tool_calls") or (response.get("message") or {}).get("tool_calls")),
            content_preview=(response.get("content") or "")[:200],
        )

        # Debug logging
        if ctx.ui_callback and hasattr(ctx.ui_callback, "on_debug"):
            success = response.get("success", False)
            ctx.ui_callback.on_debug(
                f"LLM response (success={success}, latency={latency_ms}ms)", "LLM"
            )

        # Handle errors
        if not response["success"]:
            return self._handle_llm_error(response, ctx)

        # Parse response - now includes reasoning_content
        content, tool_calls, reasoning_content = self._parse_llm_response(response)
        self._current_reasoning_content = reasoning_content  # Track for persistence
        self._current_token_usage = response.get("usage")  # Track token usage

        # Log what the LLM decided to do
        _debug_log(
            f"[LLM_DECISION] content_len={len(content)}, "
            f"tool_calls={[tc['function']['name'] for tc in (tool_calls or [])]}"
        )

        # Display reasoning content via UI callback if thinking mode is ON
        # The visibility check is done inside on_thinking() which checks chat_app._thinking_visible
        if reasoning_content and ctx.ui_callback:
            if hasattr(ctx.ui_callback, "on_thinking"):
                ctx.ui_callback.on_thinking(reasoning_content)

        # Notify thinking complete
        if ctx.ui_callback and hasattr(ctx.ui_callback, "on_thinking_complete"):
            ctx.ui_callback.on_thinking_complete()

        # Record agent response
        self._record_agent_response(content, tool_calls)

        # Dispatch based on tool calls presence
        if not tool_calls:
            return self._handle_no_tool_calls(
                ctx, content, response.get("message", {}).get("content")
            )

        # Process tool calls
        return self._process_tool_calls(
            ctx, tool_calls, content, response.get("message", {}).get("content")
        )

    def _handle_llm_error(self, response: dict, ctx: IterationContext) -> LoopAction:
        """Handle LLM errors."""
        error_text = response.get("error", "Unknown error")
        _session_debug().log("llm_call_error", "llm", error=error_text)

        if "interrupted" in error_text.lower():
            self._last_error = error_text
            # Clear tracked values without persisting interrupt message
            # The interrupt message is already shown by ui_callback.on_interrupt()
            # We don't need to add a redundant message to the session
            self._current_thinking_trace = None
            self._current_reasoning_content = None
            self._current_token_usage = None

            if ctx.ui_callback and hasattr(ctx.ui_callback, "on_interrupt"):
                ctx.ui_callback.on_interrupt()
            elif not ctx.ui_callback:
                self.console.print(
                    "  ⎿  [bold red]Interrupted · What should I do instead?[/bold red]"
                )
        else:
            self.console.print(f"[red]Error: {error_text}[/red]")
            # Include tracked metadata when persisting error
            fallback = ChatMessage(
                role=Role.ASSISTANT,
                content=f"{error_text}",
                thinking_trace=self._current_thinking_trace,
                reasoning_content=self._current_reasoning_content,
                token_usage=self._current_token_usage,
                metadata={"is_error": True},
            )
            self._last_error = error_text
            self.session_manager.add_message(fallback, self.config.auto_save_interval)
            # Clear tracked values after persistence
            self._current_thinking_trace = None
            self._current_reasoning_content = None
            self._current_token_usage = None

            if ctx.ui_callback and hasattr(ctx.ui_callback, "on_assistant_message"):
                ctx.ui_callback.on_assistant_message(fallback.content)

        return LoopAction.BREAK

    def _parse_llm_response(self, response: dict) -> tuple[str, list, Optional[str]]:
        """Parse LLM response into content, tool calls, and reasoning.

        Returns:
            Tuple of (content, tool_calls, reasoning_content):
            - content: The assistant's text response
            - tool_calls: List of tool calls to execute
            - reasoning_content: Native thinking/reasoning from models like o1 (may be None)
        """
        message_payload = response.get("message", {}) or {}
        raw_llm_content = message_payload.get("content")
        llm_description = response.get("content", raw_llm_content or "")

        tool_calls = response.get("tool_calls")
        if tool_calls is None:
            tool_calls = message_payload.get("tool_calls")

        # Extract reasoning_content for OpenAI reasoning models (o1, o3, etc.)
        reasoning_content = response.get("reasoning_content")

        return (llm_description or "").strip(), tool_calls, reasoning_content

    def _record_agent_response(self, content: str, tool_calls: Optional[list]):
        """Record agent response for ACE learning."""
        if hasattr(self._tool_executor, "set_last_agent_response"):
            self._tool_executor.set_last_agent_response(
                str(AgentResponse(content=content, tool_calls=tool_calls or []))
            )

    def _handle_no_tool_calls(
        self, ctx: IterationContext, content: str, raw_content: Optional[str]
    ) -> LoopAction:
        """Handle case where agent made no tool calls."""
        # Check if last tool failed
        last_tool_failed = False
        for msg in reversed(ctx.messages):
            if msg.get("role") == "tool":
                msg_content = msg.get("content", "")
                if msg_content.startswith("Error:"):
                    last_tool_failed = True
                break

        if last_tool_failed:
            return self._handle_failed_tool_nudge(ctx, content, raw_content)

        # Accept implicit completion
        if not content:
            content = "Warning: model returned no reply."

        self._display_message(content, ctx.ui_callback, dim=True)
        self._add_assistant_message(content, raw_content)
        return LoopAction.BREAK

    def _handle_failed_tool_nudge(
        self, ctx: IterationContext, content: str, raw_content: Optional[str]
    ) -> LoopAction:
        """Nudge agent to retry after failure."""
        ctx.consecutive_no_tool_calls += 1

        if ctx.consecutive_no_tool_calls >= self.MAX_NUDGE_ATTEMPTS:
            if not content:
                content = "Warning: could not complete after multiple attempts."

            self._display_message(content, ctx.ui_callback, dim=True)
            self._add_assistant_message(content, raw_content)
            return LoopAction.BREAK

        # Nudge
        if content:
            ctx.messages.append({"role": "assistant", "content": raw_content or content})
            self._display_message(content, ctx.ui_callback)

        ctx.messages.append(
            {
                "role": "user",
                "content": get_injection("failed_tool_nudge"),
            }
        )
        return LoopAction.CONTINUE

    def _process_tool_calls(
        self, ctx: IterationContext, tool_calls: list, content: str, raw_content: Optional[str]
    ) -> LoopAction:
        """Process a list of tool calls."""
        import json

        # Reset no-tool-call counter
        ctx.consecutive_no_tool_calls = 0

        # Check for task completion FIRST (before displaying content)
        # This prevents duplicate ⏺ bullets (one for content, one for summary)
        task_complete_call = next(
            (tc for tc in tool_calls if tc["function"]["name"] == "task_complete"), None
        )
        if task_complete_call:
            args = json.loads(task_complete_call["function"]["arguments"])
            summary = args.get("summary", "Task completed")
            self._display_message(summary, ctx.ui_callback, dim=True)
            self._add_assistant_message(summary, raw_content)
            return LoopAction.BREAK

        # Display thinking (only when NOT task_complete)
        if content:
            self._display_message(content, ctx.ui_callback)

        # Add assistant message to history
        ctx.messages.append(
            {
                "role": "assistant",
                "content": raw_content,
                "tool_calls": tool_calls,
            }
        )

        # Track reads for nudging
        all_reads = all(tc["function"]["name"] in self.READ_OPERATIONS for tc in tool_calls)
        ctx.consecutive_reads = ctx.consecutive_reads + 1 if all_reads else 0

        # Execute tools (parallel ONLY for spawn_subagent, sequential for others)
        spawn_calls = [tc for tc in tool_calls if tc["function"]["name"] == "spawn_subagent"]
        is_all_spawn_agents = len(spawn_calls) == len(tool_calls) and len(spawn_calls) > 1

        if is_all_spawn_agents:
            # All spawn_subagent - execute in parallel with special UI handling
            tool_results_by_id, operation_cancelled = self._execute_tools_parallel(tool_calls, ctx)
        else:
            # Sequential execution for all other tool calls
            tool_results_by_id = {}
            operation_cancelled = False
            for tool_call in tool_calls:
                result = self._execute_single_tool(tool_call, ctx)
                tool_results_by_id[tool_call["id"]] = result
                if result.get("interrupted", False):
                    operation_cancelled = True
                    break

        # Batch add all results after completion (maintains message order)
        for tool_call in tool_calls:
            self._add_tool_result_to_history(
                ctx.messages, tool_call, tool_results_by_id[tool_call["id"]]
            )

        if operation_cancelled:
            return LoopAction.BREAK

        # Persist and Learn
        _debug_log("[TOOLS] Before _persist_step")
        self._persist_step(ctx, tool_calls, tool_results_by_id, content, raw_content)
        _debug_log("[TOOLS] After _persist_step")

        # Check nudge for reads
        if self._should_nudge_agent(ctx.consecutive_reads, ctx.messages):
            ctx.consecutive_reads = 0

        _debug_log("[TOOLS] Returning LoopAction.CONTINUE")
        return LoopAction.CONTINUE

    def _execute_single_tool(
        self, tool_call: dict, ctx: IterationContext, suppress_separate_response: bool = False
    ) -> dict:
        """Execute a single tool and handle UI updates.

        Args:
            tool_call: The tool call dict from LLM response
            ctx: Iteration context with registry, callbacks, etc.
            suppress_separate_response: If True, don't display separate_response immediately.
                Used in parallel mode to aggregate responses later.
        """
        tool_name = tool_call["function"]["name"]

        if tool_name == "task_complete":
            return {}

        # Debug
        if ctx.ui_callback and hasattr(ctx.ui_callback, "on_debug"):
            ctx.ui_callback.on_debug(f"Executing tool: {tool_name}", "TOOL")

        args_str = tool_call["function"]["arguments"]
        _session_debug().log(
            "tool_call_start", "tool", name=tool_name, params_preview=args_str[:200]
        )

        # Notify UI call
        if ctx.ui_callback and hasattr(ctx.ui_callback, "on_tool_call"):
            ctx.ui_callback.on_tool_call(tool_name, args_str)

        # Execute
        import time as _time

        tool_start = _time.monotonic()
        try:
            result = self._execute_tool_call(
                tool_call,
                ctx.tool_registry,
                ctx.approval_manager,
                ctx.undo_manager,
                ui_callback=ctx.ui_callback,
            )
        except Exception as exc:
            import traceback

            _session_debug().log(
                "tool_call_error",
                "tool",
                name=tool_name,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            raise
        tool_duration_ms = int((_time.monotonic() - tool_start) * 1000)

        result_preview = (result.get("output") or result.get("error") or "")[:200]
        _session_debug().log(
            "tool_call_end",
            "tool",
            name=tool_name,
            duration_ms=tool_duration_ms,
            success=result.get("success", False),
            result_preview=result_preview,
        )

        # Store summary
        self._last_operation_summary = format_tool_call(
            tool_name, json.loads(args_str)
        )

        # Notify UI result
        if ctx.ui_callback and hasattr(ctx.ui_callback, "on_tool_result"):
            ctx.ui_callback.on_tool_result(tool_name, args_str, result)

        # Handle subagent display (suppress in parallel mode for aggregation)
        separate_response = result.get("separate_response")
        if separate_response and not suppress_separate_response:
            self._display_message(separate_response, ctx.ui_callback)

        return result

    def _execute_tools_parallel(
        self, tool_calls: list, ctx: IterationContext
    ) -> tuple[Dict[str, dict], bool]:
        """Execute tools in parallel using managed thread pool.

        Uses `with` statement to ensure executor cleanup (no memory leaks).
        ThreadPoolExecutor's max_workers naturally limits concurrency.

        Args:
            tool_calls: List of tool call dicts from LLM response
            ctx: Iteration context with registry, callbacks, etc.

        Returns:
            Tuple of (results_by_id dict, operation_cancelled bool)
        """
        tool_results_by_id: Dict[str, dict] = {}
        operation_cancelled = False
        ui_callback = ctx.ui_callback

        # Check if ALL tools are spawn_subagent (parallel agent scenario)
        spawn_calls = [tc for tc in tool_calls if tc["function"]["name"] == "spawn_subagent"]
        is_parallel_agents = len(spawn_calls) == len(tool_calls) and len(spawn_calls) > 1

        # Build agent info mapping (tool_call_id -> agent info)
        # Pass full agent info to UI for individual agent tracking
        agent_name_map: Dict[str, str] = {}
        if is_parallel_agents and ui_callback:
            # Collect full agent info for each parallel agent
            agent_infos: list[dict] = []
            for tc in spawn_calls:
                args = json.loads(tc["function"]["arguments"])
                agent_type = args.get("subagent_type", "Agent")
                description = args.get("description", "")
                tool_call_id = tc["id"]
                # Map tool_call_id to base type (for completion tracking)
                agent_name_map[tool_call_id] = agent_type
                # Collect full info for UI display
                agent_infos.append(
                    {
                        "agent_type": agent_type,
                        "description": description,
                        "tool_call_id": tool_call_id,
                    }
                )
            if hasattr(ui_callback, "on_parallel_agents_start"):
                import sys

                print(
                    f"[DEBUG] on_parallel_agents_start with agent_infos={agent_infos}",
                    file=sys.stderr,
                )
                ui_callback.on_parallel_agents_start(agent_infos)

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TOOLS) as executor:
            # Submit all tasks
            # For parallel agents, suppress individual separate_response display for aggregation
            future_to_call = {
                executor.submit(
                    self._execute_single_tool,
                    tc,
                    ctx,
                    suppress_separate_response=is_parallel_agents,
                ): tc
                for tc in tool_calls
            }

            # Collect results as they complete
            for future in as_completed(future_to_call):
                tool_call = future_to_call[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = {"success": False, "error": str(e)}

                tool_results_by_id[tool_call["id"]] = result
                if result.get("interrupted"):
                    operation_cancelled = True

                # Track individual agent completion for parallel agents
                if is_parallel_agents and ui_callback:
                    tool_name = tool_call["function"]["name"]
                    if tool_name == "spawn_subagent":
                        # Pass tool_call_id for individual agent tracking
                        tool_call_id = tool_call["id"]
                        success = result.get("success", True) if isinstance(result, dict) else True
                        if hasattr(ui_callback, "on_parallel_agent_complete"):
                            ui_callback.on_parallel_agent_complete(tool_call_id, success)

        # Notify UI that all parallel agents are done
        if is_parallel_agents and ui_callback:
            if hasattr(ui_callback, "on_parallel_agents_done"):
                ui_callback.on_parallel_agents_done()

        return tool_results_by_id, operation_cancelled

    def _add_tool_result_to_history(self, messages: list, tool_call: dict, result: dict):
        """Add tool execution result to message history."""
        tool_name = tool_call["function"]["name"]

        separate_response = result.get("separate_response")
        completion_status = result.get("completion_status")

        if result.get("success", False):
            tool_result = separate_response if separate_response else result.get("output", "")
            # Prepend completion status so LLM can see it (critical for subagent results)
            if completion_status:
                tool_result = f"[completion_status={completion_status}]\n{tool_result}"
        else:
            tool_result = f"Error: {result.get('error', 'Tool execution failed')}"

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": tool_result,
            }
        )

    def _persist_step(
        self,
        ctx: IterationContext,
        tool_calls: list,
        results: Dict[str, dict],
        content: str,
        raw_content: Optional[str],
    ):
        """Persist the step to session manager and record learnings."""
        tool_call_objects = []

        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            _debug_log(f"[PERSIST] Processing tool call: {tool_name}")
            if tool_name == "task_complete":
                continue

            full_result = results.get(tc["id"], {})
            _debug_log(f"[PERSIST] full_result keys: {list(full_result.keys())}")
            tool_error = full_result.get("error") if not full_result.get("success", True) else None
            tool_result_str = (
                full_result.get("output", "") if full_result.get("success", True) else None
            )
            result_summary = summarize_tool_result(tool_name, tool_result_str, tool_error)
            _debug_log(
                f"[PERSIST] result_summary: {result_summary[:100] if result_summary else None}"
            )

            nested_calls = []
            if (
                tool_name == "spawn_subagent"
                and ctx.ui_callback
                and hasattr(ctx.ui_callback, "get_and_clear_nested_calls")
            ):
                nested_calls = ctx.ui_callback.get_and_clear_nested_calls()

            _debug_log("[PERSIST] Creating ToolCallModel")
            tool_call_objects.append(
                ToolCallModel(
                    id=tc["id"],
                    name=tool_name,
                    parameters=json.loads(tc["function"]["arguments"]),
                    result=full_result,
                    result_summary=result_summary,
                    error=tool_error,
                    approved=True,
                    nested_tool_calls=nested_calls,
                )
            )
            _debug_log("[PERSIST] ToolCallModel created")

        if tool_call_objects or content:
            _debug_log(f"[PERSIST] Creating msg with {len(tool_call_objects)} tool calls")
            _debug_log(
                f"[PERSIST] content={content[:50] if content else None}, raw_content={raw_content[:50] if raw_content else None}"
            )
            metadata = {"raw_content": raw_content} if raw_content is not None else {}
            _debug_log("[PERSIST] About to create ChatMessage")
            try:
                assistant_msg = ChatMessage(
                    role=Role.ASSISTANT,
                    content=content or "",
                    metadata=metadata,
                    tool_calls=tool_call_objects,
                    # Include tracked iteration data for session persistence
                    thinking_trace=self._current_thinking_trace,
                    reasoning_content=self._current_reasoning_content,
                    token_usage=self._current_token_usage,
                )
                _debug_log("[PERSIST] ChatMessage created successfully")
            except Exception as e:
                _debug_log(f"[PERSIST] ChatMessage creation failed: {e}")
                raise

            # Sync summarizer cache to session metadata before saving
            _debug_log("[PERSIST] Syncing summarizer cache")
            try:
                cache_data = self._conversation_summarizer.to_dict()
                if cache_data and self.session_manager.current_session:
                    self.session_manager.current_session.metadata["conversation_summary"] = (
                        cache_data
                    )
            except Exception as e:
                _debug_log(f"[PERSIST] Cache sync failed: {e}")

            _debug_log("[PERSIST] Calling add_message")
            self.session_manager.add_message(assistant_msg, self.config.auto_save_interval)

            _debug_log("[PERSIST] Clearing tracked values")
            # Clear tracked values after persistence
            self._current_thinking_trace = None
            self._current_reasoning_content = None
            self._current_token_usage = None

        _debug_log("[PERSIST] Completed")

        if tool_call_objects:
            outcome = "error" if any(tc.error for tc in tool_call_objects) else "success"
            self._tool_executor.record_tool_learnings(
                ctx.query, tool_call_objects, outcome, ctx.agent
            )

    def _display_message(self, message: str, ui_callback, dim: bool = False):
        """Display a message via UI callback or console."""
        if not message:
            return

        if ui_callback and hasattr(ui_callback, "on_assistant_message"):
            ui_callback.on_assistant_message(message)
        else:
            style = "[dim]" if dim else ""
            end_style = "[/dim]" if dim else ""
            self.console.print(f"\n{style}{message}{end_style}")

    def _add_assistant_message(self, content: str, raw_content: Optional[str]):
        """Add assistant message to session."""
        metadata = {"raw_content": raw_content} if raw_content is not None else {}
        assistant_msg = ChatMessage(
            role=Role.ASSISTANT,
            content=content,
            metadata=metadata,
            # Include tracked iteration data for session persistence
            thinking_trace=self._current_thinking_trace,
            reasoning_content=self._current_reasoning_content,
            token_usage=self._current_token_usage,
        )
        self.session_manager.add_message(assistant_msg, self.config.auto_save_interval)

        # Clear tracked values after persistence
        self._current_thinking_trace = None
        self._current_reasoning_content = None
        self._current_token_usage = None

    def _should_nudge_agent(self, consecutive_reads: int, messages: list) -> bool:
        """Check if agent should be nudged to conclude."""
        if consecutive_reads >= 5:
            # Silently nudge the agent
            messages.append(
                {
                    "role": "user",
                    "content": get_injection("consecutive_reads_nudge"),
                }
            )
            return True
        return False

    def _execute_tool_call(
        self,
        tool_call: dict,
        tool_registry,
        approval_manager,
        undo_manager,
        ui_callback=None,
    ) -> dict:
        """Execute a single tool call."""

        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])
        tool_call_id = tool_call["id"]
        tool_call_display = format_tool_call(tool_name, tool_args)

        tool_monitor = TaskMonitor()
        tool_monitor.start(tool_call_display, initial_tokens=0)

        if self._tool_executor:
            self._tool_executor._current_task_monitor = tool_monitor

        progress = TaskProgressDisplay(self.console, tool_monitor)
        progress.start()

        try:
            result = tool_registry.execute_tool(
                tool_name,
                tool_args,
                mode_manager=self._tool_executor.mode_manager,
                approval_manager=approval_manager,
                undo_manager=undo_manager,
                task_monitor=tool_monitor,
                session_manager=self.session_manager,
                ui_callback=ui_callback,
                tool_call_id=tool_call_id,  # Pass for subagent parent tracking
            )
            return result
        finally:
            progress.stop()
            if self._tool_executor:
                self._tool_executor._current_task_monitor = None
