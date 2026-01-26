"""Anthropic API adapter for handling Anthropic-specific request/response formats."""

from typing import Any, Dict, List, Optional
import requests


class AnthropicAdapter:
    """Adapter for Anthropic's API which uses a different format than OpenAI."""

    def __init__(self, api_key: str, api_url: str = "https://api.anthropic.com/v1/messages"):
        self.api_key = api_key
        self.api_url = api_url
        self.headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

    def convert_request(self, openai_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Convert OpenAI-style payload to Anthropic format.

        Anthropic differences:
        - Requires max_tokens (not optional)
        - tool_choice format is different: {"type": "auto"} instead of "auto"
        - System message must be extracted from messages array
        """
        messages = openai_payload.get("messages", [])

        # Extract system message if present
        system_content = None
        filtered_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")
            else:
                filtered_messages.append(msg)

        anthropic_payload = {
            "model": openai_payload["model"],
            "max_tokens": openai_payload.get("max_tokens", 4096),
            "messages": filtered_messages,
        }

        if system_content:
            anthropic_payload["system"] = system_content

        # Convert temperature if present
        if "temperature" in openai_payload:
            anthropic_payload["temperature"] = openai_payload["temperature"]

        # Convert tools if present
        if "tools" in openai_payload and openai_payload["tools"]:
            anthropic_payload["tools"] = self._convert_tools(openai_payload["tools"])

        # Convert tool_choice if present
        if "tool_choice" in openai_payload:
            tool_choice = openai_payload["tool_choice"]
            if tool_choice == "auto":
                anthropic_payload["tool_choice"] = {"type": "auto"}
            elif tool_choice == "none":
                # Anthropic doesn't have explicit "none", so omit tools instead
                pass
            elif isinstance(tool_choice, dict):
                # Specific tool choice: {"type": "function", "function": {"name": "tool_name"}}
                anthropic_payload["tool_choice"] = {
                    "type": "tool",
                    "name": tool_choice.get("function", {}).get("name")
                }

        return anthropic_payload

    def _convert_tools(self, openai_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI tool format to Anthropic format."""
        anthropic_tools = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                anthropic_tools.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                })
        return anthropic_tools

    def convert_response(self, anthropic_response: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Anthropic response to OpenAI format.

        Anthropic response structure:
        {
          "id": "msg_...",
          "type": "message",
          "role": "assistant",
          "content": [
            {"type": "text", "text": "..."},
            {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
          ],
          "stop_reason": "end_turn" or "tool_use"
        }

        OpenAI format:
        {
          "choices": [{
            "message": {
              "role": "assistant",
              "content": "...",
              "tool_calls": [...]
            }
          }]
        }
        """
        content_blocks = anthropic_response.get("content", [])

        # Extract text content and tool calls
        text_content = ""
        tool_calls = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": self._serialize_arguments(block.get("input", {})),
                    }
                })

        # Build OpenAI-style response
        message = {
            "role": "assistant",
            "content": text_content or None,
        }

        if tool_calls:
            message["tool_calls"] = tool_calls

        return {
            "id": anthropic_response.get("id", ""),
            "object": "chat.completion",
            "model": anthropic_response.get("model", ""),
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": self._convert_stop_reason(anthropic_response.get("stop_reason")),
            }],
            "usage": self._convert_usage(anthropic_response.get("usage", {})),
        }

    def _serialize_arguments(self, args: Dict[str, Any]) -> str:
        """Serialize arguments to JSON string."""
        import json
        return json.dumps(args)

    def _convert_stop_reason(self, anthropic_reason: Optional[str]) -> str:
        """Convert Anthropic stop reason to OpenAI finish_reason."""
        mapping = {
            "end_turn": "stop",
            "tool_use": "tool_calls",
            "max_tokens": "length",
            "stop_sequence": "stop",
        }
        return mapping.get(anthropic_reason or "", "stop")

    def _convert_usage(self, anthropic_usage: Dict[str, Any]) -> Dict[str, int]:
        """Convert Anthropic usage to OpenAI format."""
        return {
            "prompt_tokens": anthropic_usage.get("input_tokens", 0),
            "completion_tokens": anthropic_usage.get("output_tokens", 0),
            "total_tokens": anthropic_usage.get("input_tokens", 0) + anthropic_usage.get("output_tokens", 0),
        }

    def post_json(self, payload: Dict[str, Any], *, task_monitor: Any = None) -> Any:
        """Make a request to Anthropic API.

        Converts the payload and response to match OpenAI format for compatibility.
        """
        from dataclasses import dataclass
        from typing import Union
        import json

        @dataclass
        class HttpResult:
            success: bool
            response: Union[requests.Response, None] = None
            error: Union[str, None] = None
            interrupted: bool = False

        @dataclass
        class MockResponse:
            """Mock response object that mimics requests.Response for compatibility."""
            status_code: int
            _json_data: Dict[str, Any]
            text: str

            def json(self):
                return self._json_data

        try:
            # Convert OpenAI-style payload to Anthropic format
            anthropic_payload = self.convert_request(payload)

            # Make request with extended timeout for long LLM responses
            # (connect_timeout=10s, read_timeout=300s)
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=anthropic_payload,
                timeout=(10, 300),
            )

            if response.status_code != 200:
                # Return actual response for error handling
                return HttpResult(success=True, response=response)

            # Convert Anthropic response to OpenAI format
            anthropic_data = response.json()
            openai_data = self.convert_response(anthropic_data)

            # Create mock response with converted data
            mock_response = MockResponse(
                status_code=200,
                _json_data=openai_data,
                text=json.dumps(openai_data)
            )

            return HttpResult(success=True, response=mock_response)

        except Exception as exc:
            return HttpResult(success=False, error=str(exc))
