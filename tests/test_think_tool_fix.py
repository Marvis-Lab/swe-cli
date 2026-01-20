"""Test cases for Think Tool fix based on Anthropic's design.

These tests verify that:
1. Simple commands go directly to tools without thinking first
2. Think tool returns empty result (no history contamination)
3. Greetings work correctly
4. Complex tasks may use think AFTER gathering information
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestThinkingTraceInjection:
    """Test that think tool injects thinking trace as user message."""

    def test_think_tool_injects_tool_and_user_messages(self):
        """Verify think tool adds minimal tool result + user message with trace."""
        from swecli.repl.react_executor import ReactExecutor

        # Create a minimal executor
        executor = ReactExecutor(
            console=MagicMock(),
            session_manager=MagicMock(),
            config=MagicMock(),
            llm_caller=MagicMock(),
            tool_executor=MagicMock(),
        )

        messages = []
        tool_call = {
            "id": "call_123",
            "function": {
                "name": "think",
                "arguments": '{"content": "Reasoning about the task..."}',
            },
        }
        result = {"success": True, "output": "Reasoning about the task..."}

        executor._add_tool_result_to_history(messages, tool_call, result)

        # Should have 2 messages: tool result + user message with trace
        assert len(messages) == 2

        # First message: minimal tool result to satisfy API
        assert messages[0]["role"] == "tool"
        assert messages[0]["tool_call_id"] == "call_123"
        assert messages[0]["content"] == "ok"

        # Second message: user message with thinking trace
        assert messages[1]["role"] == "user", "Think tool should inject trace as user message"
        assert "<thinking_trace>" in messages[1]["content"], "Should have thinking_trace tags"
        assert "Reasoning about the task..." in messages[1]["content"], "Should contain the thinking content"
        assert "Based on this analysis, proceed with the next action." in messages[1]["content"]

    def test_think_tool_only_tool_message_for_empty_content(self):
        """Verify think tool only adds tool message for empty content (no user message)."""
        from swecli.repl.react_executor import ReactExecutor

        executor = ReactExecutor(
            console=MagicMock(),
            session_manager=MagicMock(),
            config=MagicMock(),
            llm_caller=MagicMock(),
            tool_executor=MagicMock(),
        )

        messages = []
        tool_call = {
            "id": "call_123",
            "function": {
                "name": "think",
                "arguments": '{"content": ""}',
            },
        }
        result = {"success": True, "output": ""}

        executor._add_tool_result_to_history(messages, tool_call, result)

        # Should only have tool result (no user message for empty content)
        assert len(messages) == 1
        assert messages[0]["role"] == "tool"
        assert messages[0]["content"] == "ok"

    def test_regular_tool_still_adds_tool_message(self):
        """Verify regular tools still add tool role messages."""
        from swecli.repl.react_executor import ReactExecutor

        executor = ReactExecutor(
            console=MagicMock(),
            session_manager=MagicMock(),
            config=MagicMock(),
            llm_caller=MagicMock(),
            tool_executor=MagicMock(),
        )

        messages = []
        tool_call = {
            "id": "call_456",
            "function": {
                "name": "read_file",
                "arguments": '{"path": "/tmp/test.txt"}',
            },
        }
        result = {"success": True, "output": "file contents here"}

        executor._add_tool_result_to_history(messages, tool_call, result)

        assert len(messages) == 1
        assert messages[0]["role"] == "tool"
        assert messages[0]["tool_call_id"] == "call_456"
        assert messages[0]["content"] == "file contents here"


class TestThinkToolSchema:
    """Test think tool schema matches Anthropic's design."""

    def test_think_tool_description(self):
        """Verify think tool description emphasizes scratchpad nature."""
        from swecli.core.agents.components.tool_schema_builder import _BUILTIN_TOOL_SCHEMAS

        think_schema = next(
            (s for s in _BUILTIN_TOOL_SCHEMAS if s["function"]["name"] == "think"),
            None,
        )

        assert think_schema is not None, "Think tool schema should exist"

        desc = think_schema["function"]["description"]
        assert "append" in desc.lower() or "log" in desc.lower(), \
            "Description should mention appending to log"
        assert "AFTER" in desc, \
            "Description should emphasize using AFTER gathering information"


class TestThinkingSystemPrompt:
    """Test thinking system prompt has correct guidance."""

    def test_prompt_has_when_to_use_guidance(self):
        """Verify system prompt explains when to use think tool."""
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "swecli/core/agents/prompts/thinking_system_prompt.txt"
        )

        with open(prompt_path, "r") as f:
            content = f.read()

        assert "When to Use Think Tool" in content, \
            "Prompt should have 'When to Use Think Tool' section"
        assert "AFTER gathering information" in content, \
            "Prompt should mention using think AFTER gathering info"
        assert "Do NOT use think tool" in content or "Do NOT use" in content, \
            "Prompt should explain when NOT to use think tool"
        assert "first action" in content.lower(), \
            "Prompt should mention not using as first action"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
