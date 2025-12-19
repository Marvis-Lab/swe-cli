"""Primary agent implementation for interactive sessions."""

from __future__ import annotations

import json
from typing import Any, Optional

from swecli.core.base.abstract import BaseAgent
from swecli.core.agents.components import (
    ResponseCleaner,
    SystemPromptBuilder,
    ToolSchemaBuilder,
    build_max_tokens_param,
    create_http_client,
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
        self._http_client = create_http_client(config)
        self._response_cleaner = ResponseCleaner()
        self._working_dir = working_dir
        super().__init__(config, tool_registry, mode_manager)

    def build_system_prompt(self) -> str:
        return SystemPromptBuilder(self.tool_registry, self._working_dir).build()

    def build_tool_schemas(self) -> list[dict[str, Any]]:
        return ToolSchemaBuilder(self.tool_registry).build()

    def call_llm(self, messages: list[dict], task_monitor: Optional[Any] = None) -> dict:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "tools": self.tool_schemas,
            "tool_choice": "auto",
            "temperature": self.config.temperature,
            **build_max_tokens_param(self.config.model, self.config.max_tokens),
        }

        result = self._http_client.post_json(payload, task_monitor=task_monitor)
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
                "temperature": self.config.temperature,
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
                return {
                    "content": cleaned_content or "",
                    "messages": messages,
                    "success": True,
                }

            for tool_call in message_data["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_args = json.loads(tool_call["function"]["arguments"])

                # Notify UI callback before tool execution
                if ui_callback and hasattr(ui_callback, "on_tool_call"):
                    ui_callback.on_tool_call(tool_name, tool_args)

                # Check if this is a subagent (has overridden system prompt)
                is_subagent = hasattr(self, "_subagent_system_prompt") and self._subagent_system_prompt is not None

                result = self.tool_registry.execute_tool(
                    tool_name,
                    tool_args,
                    mode_manager=deps.mode_manager,
                    approval_manager=deps.approval_manager,
                    undo_manager=deps.undo_manager,
                    is_subagent=is_subagent,
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
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_result,
                    }
                )
