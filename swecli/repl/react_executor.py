"""ReAct loop executor."""

import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional, Dict, Any, List

from swecli.models.message import ChatMessage, Role, ToolCall as ToolCallModel
from swecli.core.context_engineering.memory import AgentResponse
from swecli.core.runtime.monitoring import TaskMonitor
from swecli.ui_textual.utils.tool_display import format_tool_call
from swecli.ui_textual.components.task_progress import TaskProgressDisplay
from swecli.core.utils.tool_result_summarizer import summarize_tool_result

if TYPE_CHECKING:
    from rich.console import Console
    from swecli.core.context_engineering.history import SessionManager
    from swecli.models.config import Config
    from swecli.repl.llm_caller import LLMCaller
    from swecli.repl.tool_executor import ToolExecutor
    from swecli.core.runtime.approval import ApprovalManager
    from swecli.core.context_engineering.history import UndoManager


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


class ReactExecutor:
    """Executes ReAct loop (Reasoning → Acting → Observing)."""
    
    READ_OPERATIONS = {"read_file", "list_files", "search_code"}
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

    def execute(
        self,
        query: str,
        messages: list,
        agent,
        tool_registry,
        approval_manager: "ApprovalManager",
        undo_manager: "UndoManager",
        ui_callback=None,
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
            ui_callback=ui_callback
        )

        # Notify UI start
        if ui_callback and hasattr(ui_callback, 'on_thinking_start'):
            ui_callback.on_thinking_start()

        # Debug: Query processing started
        if ui_callback and hasattr(ui_callback, 'on_debug'):
            ui_callback.on_debug(f"Processing query: {query[:50]}{'...' if len(query) > 50 else ''}", "QUERY")

        try:
            while True:
                ctx.iteration_count += 1
                action = self._run_iteration(ctx)
                if action == LoopAction.BREAK:
                    break
        except Exception as e:
            self.console.print(f"[red]Error: {str(e)}[/red]")
            import traceback
            traceback.print_exc()
            self._last_error = str(e)
            
        return (self._last_operation_summary, self._last_error, self._last_latency_ms)

    def _run_iteration(self, ctx: IterationContext) -> LoopAction:
        """Run a single ReAct iteration."""
        
        # Debug logging
        if ctx.ui_callback and hasattr(ctx.ui_callback, 'on_debug'):
            ctx.ui_callback.on_debug(f"Calling LLM with {len(ctx.messages)} messages", "LLM")

        # Call LLM
        task_monitor = TaskMonitor()
        response, latency_ms = self._llm_caller.call_llm_with_progress(ctx.agent, ctx.messages, task_monitor)
        self._last_latency_ms = latency_ms

        # Debug logging
        if ctx.ui_callback and hasattr(ctx.ui_callback, 'on_debug'):
            success = response.get("success", False)
            ctx.ui_callback.on_debug(f"LLM response (success={success}, latency={latency_ms}ms)", "LLM")

        # Handle errors
        if not response["success"]:
            return self._handle_llm_error(response, ctx)

        # Parse response
        content, tool_calls = self._parse_llm_response(response)
        
        # Notify thinking complete
        if ctx.ui_callback and hasattr(ctx.ui_callback, 'on_thinking_complete'):
            ctx.ui_callback.on_thinking_complete()

        # Record agent response
        self._record_agent_response(content, tool_calls)

        # Dispatch based on tool calls presence
        if not tool_calls:
            return self._handle_no_tool_calls(ctx, content, response.get("message", {}).get("content"))
        
        # Process tool calls
        return self._process_tool_calls(ctx, tool_calls, content, response.get("message", {}).get("content"))

    def _handle_llm_error(self, response: dict, ctx: IterationContext) -> LoopAction:
        """Handle LLM errors."""
        error_text = response.get("error", "Unknown error")
        
        if "interrupted" in error_text.lower():
            self._last_error = error_text
            if ctx.ui_callback and hasattr(ctx.ui_callback, 'on_interrupt'):
                ctx.ui_callback.on_interrupt()
            elif not ctx.ui_callback:
                 self.console.print(f"  ⎿  [bold red]Interrupted · What should I do instead?[/bold red]")
        else:
            self.console.print(f"[red]Error: {error_text}[/red]")
            fallback = ChatMessage(role=Role.ASSISTANT, content=f"{error_text}")
            self._last_error = error_text
            self.session_manager.add_message(fallback, self.config.auto_save_interval)
            if ctx.ui_callback and hasattr(ctx.ui_callback, 'on_assistant_message'):
                ctx.ui_callback.on_assistant_message(fallback.content)
                
        return LoopAction.BREAK

    def _parse_llm_response(self, response: dict) -> tuple[str, list]:
        """Parse LLM response into content and tool calls."""
        message_payload = response.get("message", {}) or {}
        raw_llm_content = message_payload.get("content")
        llm_description = response.get("content", raw_llm_content or "")
        
        tool_calls = response.get("tool_calls")
        if tool_calls is None:
            tool_calls = message_payload.get("tool_calls")
            
        return (llm_description or "").strip(), tool_calls

    def _record_agent_response(self, content: str, tool_calls: Optional[list]):
        """Record agent response for ACE learning."""
        if hasattr(self._tool_executor, 'set_last_agent_response'):
            self._tool_executor.set_last_agent_response(str(AgentResponse(
                content=content,
                tool_calls=tool_calls or []
            )))

    def _handle_no_tool_calls(self, ctx: IterationContext, content: str, raw_content: Optional[str]) -> LoopAction:
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

    def _handle_failed_tool_nudge(self, ctx: IterationContext, content: str, raw_content: Optional[str]) -> LoopAction:
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

        ctx.messages.append({
            "role": "user",
            "content": "The previous operation failed. Please fix the issue and try again, or call task_complete with status='failed' if you cannot proceed.",
        })
        return LoopAction.CONTINUE

    def _process_tool_calls(
        self, 
        ctx: IterationContext, 
        tool_calls: list, 
        content: str, 
        raw_content: Optional[str]
    ) -> LoopAction:
        """Process a list of tool calls."""
        import json
        
        # Reset no-tool-call counter
        ctx.consecutive_no_tool_calls = 0

        # Display thinking
        if content:
             self._display_message(content, ctx.ui_callback)

        # Add assistant message to history
        ctx.messages.append({
            "role": "assistant",
            "content": raw_content,
            "tool_calls": tool_calls,
        })
        
        # Track reads for nudging
        all_reads = all(tc["function"]["name"] in self.READ_OPERATIONS for tc in tool_calls)
        ctx.consecutive_reads = ctx.consecutive_reads + 1 if all_reads else 0

        # Check for task completion
        task_complete_call = next((tc for tc in tool_calls if tc["function"]["name"] == "task_complete"), None)
        if task_complete_call:
             args = json.loads(task_complete_call["function"]["arguments"])
             summary = args.get("summary", "Task completed")
             self._display_message(summary, ctx.ui_callback, dim=True)
             self._add_assistant_message(summary, raw_content)
             return LoopAction.BREAK

        # Execute tools
        operation_cancelled = False
        tool_results_by_id = {}
        
        for tool_call in tool_calls:
            result = self._execute_single_tool(tool_call, ctx)
            tool_results_by_id[tool_call["id"]] = result
            
            if result.get("interrupted"):
                operation_cancelled = True
                
            # Add result to history
            self._add_tool_result_to_history(ctx.messages, tool_call, result)

        if operation_cancelled:
            return LoopAction.BREAK

        # Persist and Learn
        self._persist_step(ctx, tool_calls, tool_results_by_id, content, raw_content)
        
        # Check nudge for reads
        if self._should_nudge_agent(ctx.consecutive_reads, ctx.messages):
            ctx.consecutive_reads = 0

        return LoopAction.CONTINUE

    def _execute_single_tool(self, tool_call: dict, ctx: IterationContext) -> dict:
        """Execute a single tool and handle UI updates."""
        tool_name = tool_call["function"]["name"]
        
        if tool_name == "task_complete":
            return {}

        # Debug
        if ctx.ui_callback and hasattr(ctx.ui_callback, 'on_debug'):
            ctx.ui_callback.on_debug(f"Executing tool: {tool_name}", "TOOL")

        # Notify UI call
        if ctx.ui_callback and hasattr(ctx.ui_callback, 'on_tool_call'):
            ctx.ui_callback.on_tool_call(tool_name, tool_call["function"]["arguments"])
        
        # Execute
        result = self._execute_tool_call(
            tool_call,
            ctx.tool_registry,
            ctx.approval_manager,
            ctx.undo_manager,
            ui_callback=ctx.ui_callback,
        )
        
        # Store summary
        self._last_operation_summary = format_tool_call(
            tool_name, 
            json.loads(tool_call["function"]["arguments"])
        )

        # Notify UI result
        if ctx.ui_callback and hasattr(ctx.ui_callback, 'on_tool_result'):
            ctx.ui_callback.on_tool_result(
                tool_name,
                tool_call["function"]["arguments"],
                result
            )
            
        # Handle subagent display
        separate_response = result.get("separate_response")
        if separate_response:
            self._display_message(separate_response, ctx.ui_callback)

        return result

    def _add_tool_result_to_history(self, messages: list, tool_call: dict, result: dict):
        """Add tool execution result to message history."""
        separate_response = result.get("separate_response")
        if result.get("success", False):
            tool_result = separate_response if separate_response else result.get("output", "")
        else:
            tool_result = f"Error: {result.get('error', 'Tool execution failed')}"
        
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": tool_result,
        })

    def _persist_step(
        self, 
        ctx: IterationContext, 
        tool_calls: list, 
        results: Dict[str, dict], 
        content: str, 
        raw_content: Optional[str]
    ):
        """Persist the step to session manager and record learnings."""
        tool_call_objects = []
        
        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            if tool_name == "task_complete":
                continue

            full_result = results.get(tc["id"], {})
            tool_error = full_result.get("error") if not full_result.get("success", True) else None
            tool_result_str = full_result.get("output", "") if full_result.get("success", True) else None
            result_summary = summarize_tool_result(tool_name, tool_result_str, tool_error)
            
            nested_calls = []
            if tool_name == "spawn_subagent" and ctx.ui_callback and hasattr(ctx.ui_callback, 'get_and_clear_nested_calls'):
                nested_calls = ctx.ui_callback.get_and_clear_nested_calls()

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

        if tool_call_objects or content:
            metadata = {"raw_content": raw_content} if raw_content is not None else {}
            assistant_msg = ChatMessage(
                role=Role.ASSISTANT,
                content=content or "",
                metadata=metadata,
                tool_calls=tool_call_objects,
            )
            self.session_manager.add_message(assistant_msg, self.config.auto_save_interval)

        if tool_call_objects:
            outcome = "error" if any(tc.error for tc in tool_call_objects) else "success"
            self._tool_executor.record_tool_learnings(ctx.query, tool_call_objects, outcome, ctx.agent)

    def _display_message(self, message: str, ui_callback, dim: bool = False):
        """Display a message via UI callback or console."""
        if not message:
            return
            
        if ui_callback and hasattr(ui_callback, 'on_assistant_message'):
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
        )
        self.session_manager.add_message(assistant_msg, self.config.auto_save_interval)

    def _should_nudge_agent(self, consecutive_reads: int, messages: list) -> bool:
        """Check if agent should be nudged to conclude."""
        if consecutive_reads >= 5:
            # Silently nudge the agent
            messages.append({
                "role": "user",
                "content": "Based on what you've seen, please summarize your findings and explain what needs to be done next."
            })
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
            )
            return result
        finally:
            progress.stop()
            if self._tool_executor:
                 self._tool_executor._current_task_monitor = None
