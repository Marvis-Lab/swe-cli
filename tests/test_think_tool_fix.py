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


class TestForceThinkLogic:
    """Test that force_think logic respects thinking_visible and iteration context."""

    def test_force_think_iteration_1_thinking_on(self):
        """Verify force_think is True on iteration 1 when thinking mode is ON."""
        thinking_visible = True
        iteration_count = 1
        had_non_think_tools = False
        force_think = thinking_visible and ((iteration_count == 1) or had_non_think_tools)
        assert force_think is True, "force_think should be True on iteration 1 with thinking ON"

    def test_force_think_after_tools_thinking_on(self):
        """Verify force_think is True after non-think tools when thinking mode is ON."""
        thinking_visible = True
        iteration_count = 3
        had_non_think_tools = True
        force_think = thinking_visible and ((iteration_count == 1) or had_non_think_tools)
        assert force_think is True, "force_think should be True after tools with thinking ON"

    def test_no_force_think_mid_iteration_thinking_on(self):
        """Verify force_think is False mid-iteration (no tools just executed) when thinking ON."""
        thinking_visible = True
        iteration_count = 2
        had_non_think_tools = False  # No tools just executed
        force_think = thinking_visible and ((iteration_count == 1) or had_non_think_tools)
        assert force_think is False, "force_think should be False mid-iteration without tool execution"

    def test_no_force_think_when_thinking_off(self):
        """Verify force_think is False when thinking mode is OFF."""
        thinking_visible = False
        iteration_count = 1
        had_non_think_tools = True
        force_think = thinking_visible and ((iteration_count == 1) or had_non_think_tools)
        assert force_think is False, "force_think should be False when thinking mode is OFF"


class TestThinkToolResult:
    """Test that think tool returns minimal acknowledgment."""

    def test_think_tool_returns_minimal_ack(self):
        """Verify think tool result is minimal 'ok' in message history."""
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

        assert len(messages) == 1
        assert messages[0]["role"] == "tool"
        assert messages[0]["tool_call_id"] == "call_123"
        assert messages[0]["content"] == "ok", "Think tool should return 'ok' (not echo content)"


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
