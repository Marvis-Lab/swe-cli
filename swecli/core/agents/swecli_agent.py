"""Primary agent implementation for interactive sessions."""

from __future__ import annotations

import json
from typing import Any, Optional

from swecli.core.base.abstract import BaseAgent
from swecli.core.agents.components import (
    ResponseCleaner,
    SystemPromptBuilder,
    ThinkingPromptBuilder,
    ToolSchemaBuilder,
    build_max_tokens_param,
    build_temperature_param,
    create_http_client,
    create_http_client_for_provider,
)
from swecli.models.config import AppConfig


class WebInterruptMonitor:
    """Monitor for checking web interrupt requests."""

    def __init__(self, web_state: Any):
        self.web_state = web_state

    def should_interrupt(self) -> bool:
        """Check if interrupt has been requested."""
        return self.web_state.is_interrupt_requested()


class SwecliAgent(BaseAgent):
    """Custom agent that coordinates LLM interactions via HTTP."""

    def __init__(
        self,
        config: AppConfig,
        tool_registry: Any,
        mode_manager: Any,
        working_dir: Any = None,
    ) -> None:
        self.__http_client = None  # Lazy initialization - defer API key validation
        self.__thinking_http_client = None  # Lazy initialization for Thinking model
        self._response_cleaner = ResponseCleaner()
        self._working_dir = working_dir
        self._schema_builder = ToolSchemaBuilder(tool_registry)
        super().__init__(config, tool_registry, mode_manager)

    @property
    def _http_client(self) -> Any:
        """Lazily create HTTP client on first access (defers API key validation)."""
        if self.__http_client is None:
            self.__http_client = create_http_client(self.config)
        return self.__http_client

    @property
    def _thinking_http_client(self) -> Any:
        """Lazily create HTTP client for Thinking model provider.

        Only created if Thinking model is configured with a different provider.
        Returns None if Thinking model uses same provider as Normal model.
        """
        if self.__thinking_http_client is None:
            # Only create if thinking provider is different from normal provider
            thinking_provider = self.config.model_thinking_provider
            if thinking_provider and thinking_provider != self.config.model_provider:
                try:
                    self.__thinking_http_client = create_http_client_for_provider(
                        thinking_provider, self.config
                    )
                except ValueError:
                    # API key not set - fall back to normal client
                    return self._http_client
        return self.__thinking_http_client

    def build_system_prompt(self, thinking_visible: bool = False) -> str:
        """Build the system prompt for the agent.

        Args:
            thinking_visible: If True, use thinking-specialized prompt

        Returns:
            The formatted system prompt string
        """
        if thinking_visible:
            return ThinkingPromptBuilder(self.tool_registry, self._working_dir).build()
        return SystemPromptBuilder(self.tool_registry, self._working_dir).build()

    def build_tool_schemas(self, thinking_visible: bool = True) -> list[dict[str, Any]]:
        return self._schema_builder.build(thinking_visible=thinking_visible)

    def call_llm(
        self,
        messages: list[dict],
        task_monitor: Optional[Any] = None,
        thinking_visible: bool = True,
        iteration_count: int = 1,
    ) -> dict:
        # Select model based on thinking mode
        # When thinking is visible and Thinking model is configured, use it
        if thinking_visible and self.config.model_thinking:
            model_id = self.config.model_thinking
            # Use thinking provider's HTTP client if different from normal
            http_client = self._thinking_http_client or self._http_client
        else:
            model_id = self.config.model
            http_client = self._http_client

        # Rebuild schemas with current thinking visibility
        # This ensures think tool is filtered when thinking mode is OFF
        tool_schemas = self._schema_builder.build(thinking_visible=thinking_visible)

        # Force think tool on first iteration when thinking mode is ON
        # This ensures thinking trace is displayed for ALL queries
        # After first iteration, let model decide which tools to use
        if thinking_visible and iteration_count == 1:
            # Force specifically the think tool (not just any tool)
            tool_choice = {"type": "function", "function": {"name": "think"}}
        else:
            tool_choice = "auto"

        payload = {
            "model": model_id,  # Use selected model (Normal or Thinking)
            "messages": messages,
            "tools": tool_schemas,
            "tool_choice": tool_choice,
            **build_temperature_param(model_id, self.config.temperature),
            **build_max_tokens_param(model_id, self.config.max_tokens),
        }

        result = http_client.post_json(payload, task_monitor=task_monitor)
        if not result.success or result.response is None:
            return {
                "success": False,
                "error": result.error or "Unknown error",
                "interrupted": result.interrupted,
            }

        response = result.response
        if response.status_code != 200:
            return {
                "success": False,
                "error": f"API Error {response.status_code}: {response.text}",
            }

        response_data = response.json()
        choice = response_data["choices"][0]
        message_data = choice["message"]

        raw_content = message_data.get("content")
        cleaned_content = self._response_cleaner.clean(raw_content) if raw_content else None

        # Extract reasoning_content for OpenAI reasoning models (o1, o3, etc.)
        # This is the native thinking/reasoning trace from models like o1-preview
        reasoning_content = message_data.get("reasoning_content")

        if task_monitor and "usage" in response_data:
            usage = response_data["usage"]
            total_tokens = usage.get("total_tokens", 0)
            if total_tokens > 0:
                task_monitor.update_tokens(total_tokens)

        return {
            "success": True,
            "message": message_data,
            "content": cleaned_content,
            "tool_calls": message_data.get("tool_calls"),
            "reasoning_content": reasoning_content,  # Native thinking trace from model
            "usage": response_data.get("usage"),
        }

    def run_sync(
        self,
        message: str,
        deps: Any,
        message_history: Optional[list[dict]] = None,
        ui_callback: Optional[Any] = None,
        max_iterations: Optional[int] = None,  # None = unlimited
        task_monitor: Optional[Any] = None,  # Task monitor for interrupt support
    ) -> dict:
        messages = message_history or []

        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": self.system_prompt})

        messages.append({"role": "user", "content": message})

        iteration = 0
        consecutive_no_tool_calls = 0
        MAX_NUDGE_ATTEMPTS = 3  # After this many nudges, treat as implicit completion

        while True:
            iteration += 1

            # Safety limit only if explicitly set
            if max_iterations is not None and iteration > max_iterations:
                return {
                    "content": "Max iterations reached without completion",
                    "messages": messages,
                    "success": False,
                }

            # Check for interrupt request via task_monitor (Textual UI)
            if task_monitor is not None and task_monitor.should_interrupt():
                return {
                    "content": "Task interrupted by user",
                    "messages": messages,
                    "success": False,
                    "interrupted": True,
                }

            # Check for interrupt request (for web UI)
            if hasattr(self, 'web_state') and self.web_state.is_interrupt_requested():
                self.web_state.clear_interrupt()
                return {
                    "content": "Task interrupted by user",
                    "messages": messages,
                    "success": False,
                    "interrupted": True,
                }

            payload = {
                "model": self.config.model,
                "messages": messages,
                "tools": self.tool_schemas,
                "tool_choice": "auto",
                **build_temperature_param(self.config.model, self.config.temperature),
                **build_max_tokens_param(self.config.model, self.config.max_tokens),
            }

            # Use provided task_monitor, or create WebInterruptMonitor for web UI
            monitor = task_monitor
            if monitor is None and hasattr(self, 'web_state'):
                monitor = WebInterruptMonitor(self.web_state)

            result = self._http_client.post_json(payload, task_monitor=monitor)
            if not result.success or result.response is None:
                error_msg = result.error or "Unknown error"
                return {
                    "content": error_msg,
                    "messages": messages,
                    "success": False,
                }

            response = result.response
            if response.status_code != 200:
                error_msg = f"API Error {response.status_code}: {response.text}"
                return {
                    "content": error_msg,
                    "messages": messages,
                    "success": False,
                }

            response_data = response.json()
            choice = response_data["choices"][0]
            message_data = choice["message"]

            raw_content = message_data.get("content")
            cleaned_content = self._response_cleaner.clean(raw_content) if raw_content else None

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": raw_content or "",
            }
            if "tool_calls" in message_data and message_data["tool_calls"]:
                assistant_msg["tool_calls"] = message_data["tool_calls"]
            messages.append(assistant_msg)

            if "tool_calls" not in message_data or not message_data["tool_calls"]:
                # No tool calls - check if we should nudge or accept implicit completion
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
                        return {
                            "content": cleaned_content or "Could not complete after multiple attempts",
                            "messages": messages,
                            "success": False,
                        }

                    # Nudge agent to fix the error and retry
                    messages.append({
                        "role": "user",
                        "content": "The previous operation failed. Please fix the issue and try again, or call task_complete with status='failed' if you cannot proceed.",
                    })
                    continue

                # Last tool succeeded (or no previous tool) - accept implicit completion
                # For subagents: generate a summary before returning to parent
                is_subagent = hasattr(self, "_subagent_system_prompt") and self._subagent_system_prompt is not None

                if is_subagent:
                    # Request explicit summary for better parent context
                    summary_request = {
                        "role": "user",
                        "content": "Briefly summarize what you accomplished (2-3 sentences). Focus on key outcomes and results.",
                    }
                    messages.append(summary_request)

                    summary_result = self.call_llm(messages, task_monitor)
                    if summary_result.get("success"):
                        summary_content = self._response_cleaner.clean(
                            summary_result.get("content", "")
                        )
                        return {
                            "content": summary_content or cleaned_content or "",
                            "messages": messages,
                            "success": True,
                        }

                # Main agent or summary generation failed: return as-is
                return {
                    "content": cleaned_content or "",
                    "messages": messages,
                    "success": True,
                }

            # Reset counter when we have tool calls
            consecutive_no_tool_calls = 0

            for tool_call in message_data["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_args = json.loads(tool_call["function"]["arguments"])

                # Check for explicit task completion
                if tool_name == "task_complete":
                    summary = tool_args.get("summary", "Task completed")
                    status = tool_args.get("status", "success")
                    return {
                        "content": summary,
                        "messages": messages,
                        "success": status != "failed",
                        "completion_status": status,
                    }

                # Notify UI callback before tool execution
                if ui_callback and hasattr(ui_callback, "on_tool_call"):
                    ui_callback.on_tool_call(tool_name, tool_args)

                # Check if this is a subagent (has overridden system prompt)
                is_subagent = hasattr(self, "_subagent_system_prompt") and self._subagent_system_prompt is not None

                # Log tool registry type for debugging Docker execution
                import logging
                _logger = logging.getLogger(__name__)
                _logger.info(f"SwecliAgent executing tool: {tool_name}")
                _logger.info(f"  tool_registry type: {type(self.tool_registry).__name__}")

                result = self.tool_registry.execute_tool(
                    tool_name,
                    tool_args,
                    mode_manager=deps.mode_manager,
                    approval_manager=deps.approval_manager,
                    undo_manager=deps.undo_manager,
                    task_monitor=task_monitor,
                    is_subagent=is_subagent,
                    ui_callback=ui_callback,
                )

                # Notify UI callback after tool execution
                if ui_callback and hasattr(ui_callback, "on_tool_result"):
                    ui_callback.on_tool_result(tool_name, tool_args, result)

                # Check if tool execution was interrupted (e.g., subagent cancelled via Escape)
                if result.get("interrupted"):
                    return {
                        "content": "Task interrupted by user",
                        "messages": messages,
                        "success": False,
                        "interrupted": True,
                    }

                tool_result = (
                    result.get("output", "")
                    if result["success"]
                    else f"Error: {result.get('error', 'Tool execution failed')}"
                )
                # Append LLM-only suffix (e.g., retry prompts) - hidden from UI
                if result.get("_llm_suffix"):
                    tool_result += result["_llm_suffix"]
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_result,
                    }
                )
