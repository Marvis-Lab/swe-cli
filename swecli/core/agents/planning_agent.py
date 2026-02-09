"""Agent dedicated to PLAN mode interactions with read-only codebase exploration."""

from __future__ import annotations

import json
from typing import Any, Optional

from swecli.core.base.abstract import BaseAgent
from swecli.core.agents.components import (
    PlanningPromptBuilder,
    PlanningToolSchemaBuilder,
    ThinkingPromptBuilder,
    ResponseCleaner,
    build_max_tokens_param,
    build_temperature_param,
    create_http_client,
)
from swecli.models.config import AppConfig


class PlanningAgent(BaseAgent):
    """Planning agent that explores codebase and creates implementation plans.

    This agent has access to read-only tools for codebase exploration:
    - read_file: Read file contents
    - list_files: List directory contents
    - search: Search code with ripgrep
    - fetch_url: Fetch web documentation

    It CANNOT execute write operations or commands.
    """

    def __init__(
        self,
        config: AppConfig,
        tool_registry: Any,
        mode_manager: Any,
        working_dir: Any = None,
        env_context: Any = None,
    ) -> None:
        # Lazy initialization - defer API key validation until first API call
        self.__http_client = None
        self._response_cleaner = ResponseCleaner()
        self._working_dir = working_dir
        self._env_context = env_context
        super().__init__(config, tool_registry, mode_manager)

    @property
    def _http_client(self) -> Any:
        """Lazily create HTTP client on first access (defers API key validation)."""
        if self.__http_client is None:
            self.__http_client = create_http_client(self.config)
        return self.__http_client

    def build_system_prompt(self, thinking_visible: bool = False) -> str:
        """Build the system prompt for the planning agent.

        Args:
            thinking_visible: If True, return thinking-specialized prompt for reasoning phase.

        Returns:
            The formatted system prompt string
        """
        if thinking_visible:
            return ThinkingPromptBuilder(
                self.tool_registry, self._working_dir, env_context=self._env_context
            ).build()
        return PlanningPromptBuilder(self._working_dir, env_context=self._env_context).build()

    def call_thinking_llm(
        self,
        messages: list[dict],
        task_monitor: Optional[Any] = None,
    ) -> dict:
        """Call LLM for thinking phase only - NO tools, just reasoning.

        Args:
            messages: Conversation messages
            task_monitor: Optional monitor for tracking progress

        Returns:
            Dict with success status and thinking content
        """
        payload = {
            "model": self.config.model,
            "messages": messages,
            # NO tools - just reasoning
            **build_temperature_param(self.config.model, self.config.temperature),
            **build_max_tokens_param(self.config.model, self.config.max_tokens),
        }

        result = self._http_client.post_json(payload, task_monitor=task_monitor)
        if not result.success or result.response is None:
            return {
                "success": False,
                "error": result.error or "Unknown error",
                "content": "",
            }

        response = result.response
        if response.status_code != 200:
            return {
                "success": False,
                "error": f"API Error {response.status_code}: {response.text}",
                "content": "",
            }

        response_data = response.json()
        choice = response_data["choices"][0]
        message_data = choice["message"]
        content = message_data.get("content", "")

        return {
            "success": True,
            "content": content,
        }

    def build_tool_schemas(self) -> list[dict[str, Any]]:
        """Return read-only tool schemas for codebase exploration."""
        return PlanningToolSchemaBuilder(self.tool_registry).build()

    def call_llm(
        self,
        messages: list[dict],
        task_monitor: Optional[Any] = None,
        thinking_visible: bool = False,  # Ignored for planning agent (compatibility parameter)
    ) -> dict:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "tools": self.tool_schemas,
            "tool_choice": "auto",
            **build_temperature_param(self.config.model, self.config.temperature),
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
            "reasoning_content": reasoning_content,  # Native reasoning from o1/o3 models
            "usage": response_data.get("usage"),
        }

    def run_sync(
        self,
        message: str,
        deps: Any,
        message_history: Optional[list[dict]] = None,
        ui_callback: Optional[Any] = None,
    ) -> dict:
        """Run planning agent with read-only tool execution.

        The planning agent can use read-only tools to explore the codebase,
        but write operations are blocked by the tool registry.
        """
        messages = message_history or []
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": self.system_prompt})

        messages.append({"role": "user", "content": message})

        max_iterations = 15  # Allow more iterations for thorough exploration
        for _ in range(max_iterations):
            payload = {
                "model": self.config.model,
                "messages": messages,
                "tools": self.tool_schemas,
                "tool_choice": "auto",
                **build_temperature_param(self.config.model, self.config.temperature),
                **build_max_tokens_param(self.config.model, self.config.max_tokens),
            }

            result = self._http_client.post_json(payload)
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

            # Build assistant message
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": raw_content or "",
            }
            if "tool_calls" in message_data and message_data["tool_calls"]:
                assistant_msg["tool_calls"] = message_data["tool_calls"]
            messages.append(assistant_msg)

            # Notify UI of assistant response if callback provided
            if ui_callback and cleaned_content:
                ui_callback("assistant_message", cleaned_content)

            # If no tool calls, we're done - return the plan
            if "tool_calls" not in message_data or not message_data["tool_calls"]:
                return {
                    "content": cleaned_content or "",
                    "messages": messages,
                    "success": True,
                }

            # Execute read-only tools
            for tool_call in message_data["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                try:
                    tool_args = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError:
                    tool_args = {}

                # Notify UI of tool call if callback provided
                if ui_callback:
                    ui_callback("tool_call", {"name": tool_name, "args": tool_args})

                # Execute tool through registry (write ops are blocked)
                result = self.tool_registry.execute_tool(
                    tool_name,
                    tool_args,
                    mode_manager=deps.mode_manager if deps else None,
                    approval_manager=None,  # No approval needed for read-only
                    undo_manager=None,
                )

                tool_result = (
                    result.get("output", "")
                    if result.get("success")
                    else f"Error: {result.get('error', 'Tool execution failed')}"
                )

                # Notify UI of tool result if callback provided
                if ui_callback:
                    ui_callback(
                        "tool_result",
                        {
                            "name": tool_name,
                            "result": tool_result,
                            "success": result.get("success", False),
                        },
                    )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_result,
                    }
                )

        return {
            "content": "Max iterations reached - please continue or refine your request",
            "messages": messages,
            "success": False,
        }
