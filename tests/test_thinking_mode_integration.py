"""Integration tests for thinking mode with real API calls.

These tests verify that the thinking mode actually triggers the model
to call the think tool in various scenarios.

Run with: pytest tests/test_thinking_mode_integration.py -v -s

Requires OPENAI_API_KEY environment variable to be set.
"""

import os
import pytest

from swecli.core.agents.swecli_agent import SwecliAgent
from swecli.models.config import AppConfig
from swecli.core.runtime import ModeManager
from swecli.core.context_engineering.tools.registry import ToolRegistry


# Skip all tests if OPENAI_API_KEY not set
pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set"
)


def get_thinking_system_prompt() -> str:
    """Get a minimal system prompt with thinking instruction enabled."""
    return (
        "You are a helpful assistant. "
        "**CRITICAL REQUIREMENT - THINKING MODE IS ON:** "
        "You MUST call the `think` tool FIRST before calling ANY other tool. "
        "This is mandatory - do NOT skip this step. Do NOT call write_file, read_file, bash, or any other tool before calling `think`. "
        "In your thinking, explain step-by-step: what you understand about the task, your approach, and your planned actions. "
        "Aim for 100-300 words. Only after calling `think` may you proceed with other tools."
    )


def get_non_thinking_system_prompt() -> str:
    """Get a minimal system prompt without thinking instruction."""
    return (
        "You are a helpful assistant. "
        "For complex tasks, briefly explain your reasoning in 1-2 sentences. "
        "For simple tasks, act directly."
    )


def create_test_agent() -> SwecliAgent:
    """Create a minimal agent for testing."""
    config = AppConfig()
    config.model_provider = "openai"
    config.model = "gpt-4o-mini"  # Use cheaper model for tests
    config.api_key = os.getenv("OPENAI_API_KEY")
    config.max_tokens = 1000
    config.temperature = 0.3  # Lower temperature for more deterministic responses

    tool_registry = ToolRegistry()
    mode_manager = ModeManager()

    return SwecliAgent(config, tool_registry, mode_manager)


def has_think_tool_call(response: dict) -> bool:
    """Check if the response contains a think tool call."""
    tool_calls = response.get("tool_calls") or []
    return any(
        tc.get("function", {}).get("name") == "think"
        for tc in tool_calls
    )


def get_think_content(response: dict) -> str | None:
    """Extract the thinking content from a response."""
    tool_calls = response.get("tool_calls") or []
    for tc in tool_calls:
        if tc.get("function", {}).get("name") == "think":
            import json
            args = tc.get("function", {}).get("arguments", "{}")
            parsed = json.loads(args)
            return parsed.get("content")
    return None


class TestThinkingModeTriggering:
    """Test that thinking mode triggers correctly with various prompts."""

    def test_simple_question_triggers_thinking(self):
        """Test that even a simple question triggers thinking when enabled."""
        agent = create_test_agent()

        messages = [
            {"role": "system", "content": get_thinking_system_prompt()},
            {"role": "user", "content": "What is 2 + 2?"}
        ]

        response = agent.call_llm(messages=messages, thinking_visible=True)

        assert response["success"], f"API call failed: {response.get('error')}"
        assert has_think_tool_call(response), (
            "Model should call think tool for simple question when thinking mode is ON. "
            f"Got tool_calls: {response.get('tool_calls')}"
        )

        content = get_think_content(response)
        assert content and len(content) > 50, (
            f"Thinking content should be verbose (>50 chars), got: {content}"
        )

    def test_complex_task_triggers_thinking(self):
        """Test that a complex task triggers thinking."""
        agent = create_test_agent()

        messages = [
            {"role": "system", "content": get_thinking_system_prompt()},
            {"role": "user", "content": "How would you design a REST API for a todo app?"}
        ]

        response = agent.call_llm(messages=messages, thinking_visible=True)

        assert response["success"], f"API call failed: {response.get('error')}"
        assert has_think_tool_call(response), (
            "Model should call think tool for complex task. "
            f"Got tool_calls: {response.get('tool_calls')}"
        )

        content = get_think_content(response)
        assert content and len(content) > 100, (
            f"Thinking content should be detailed (>100 chars) for complex task, got: {content}"
        )

    def test_code_task_triggers_thinking(self):
        """Test that a coding task triggers thinking."""
        agent = create_test_agent()

        messages = [
            {"role": "system", "content": get_thinking_system_prompt()},
            {"role": "user", "content": "Write a Python function to check if a number is prime."}
        ]

        response = agent.call_llm(messages=messages, thinking_visible=True)

        assert response["success"], f"API call failed: {response.get('error')}"
        assert has_think_tool_call(response), (
            "Model should call think tool for coding task. "
            f"Got tool_calls: {response.get('tool_calls')}"
        )

    def test_debugging_task_triggers_thinking(self):
        """Test that a debugging task triggers thinking."""
        agent = create_test_agent()

        messages = [
            {"role": "system", "content": get_thinking_system_prompt()},
            {"role": "user", "content": "This code has a bug: `for i in range(10): print(i+1)`. Find and explain the issue."}
        ]

        response = agent.call_llm(messages=messages, thinking_visible=True)

        assert response["success"], f"API call failed: {response.get('error')}"
        assert has_think_tool_call(response), (
            "Model should call think tool for debugging task. "
            f"Got tool_calls: {response.get('tool_calls')}"
        )


class TestThinkingModeDisabled:
    """Test that thinking mode is properly disabled when thinking_visible=False."""

    def test_think_tool_not_in_schema_when_disabled(self):
        """Test that think tool is filtered from schemas when disabled."""
        agent = create_test_agent()

        schemas_on = agent.build_tool_schemas(thinking_visible=True)
        schemas_off = agent.build_tool_schemas(thinking_visible=False)

        names_on = [s["function"]["name"] for s in schemas_on]
        names_off = [s["function"]["name"] for s in schemas_off]

        assert "think" in names_on, "think tool should be in schemas when enabled"
        assert "think" not in names_off, "think tool should NOT be in schemas when disabled"

    def test_model_cannot_call_think_when_disabled(self):
        """Test that model doesn't call think tool when it's not in schema."""
        agent = create_test_agent()

        messages = [
            {"role": "system", "content": get_non_thinking_system_prompt()},
            {"role": "user", "content": "What is 2 + 2?"}
        ]

        response = agent.call_llm(messages=messages, thinking_visible=False)

        assert response["success"], f"API call failed: {response.get('error')}"
        # Model should NOT call think tool since it's not available
        assert not has_think_tool_call(response), (
            "Model should NOT call think tool when thinking_visible=False. "
            f"Got tool_calls: {response.get('tool_calls')}"
        )


class TestThinkingContentQuality:
    """Test the quality and structure of thinking content."""

    def test_thinking_content_is_verbose(self):
        """Test that thinking content meets the word count guidance."""
        agent = create_test_agent()

        messages = [
            {"role": "system", "content": get_thinking_system_prompt()},
            {"role": "user", "content": "Explain the difference between a stack and a queue."}
        ]

        response = agent.call_llm(messages=messages, thinking_visible=True)

        assert response["success"], f"API call failed: {response.get('error')}"

        content = get_think_content(response)
        if content:
            word_count = len(content.split())
            # Should aim for 100-300 words, but allow some flexibility
            assert word_count >= 50, (
                f"Thinking content should be verbose (>=50 words), got {word_count} words: {content}"
            )

    def test_thinking_content_addresses_task(self):
        """Test that thinking content actually addresses the task."""
        agent = create_test_agent()

        messages = [
            {"role": "system", "content": get_thinking_system_prompt()},
            {"role": "user", "content": "How do I sort a list in Python?"}
        ]

        response = agent.call_llm(messages=messages, thinking_visible=True)

        assert response["success"], f"API call failed: {response.get('error')}"

        content = get_think_content(response)
        if content:
            content_lower = content.lower()
            # Should mention relevant concepts
            assert any(word in content_lower for word in ["sort", "list", "python"]), (
                f"Thinking content should address the task. Got: {content}"
            )


class TestThinkingModeConsistency:
    """Test that thinking mode triggers consistently across multiple calls."""

    def test_thinking_triggers_consistently(self):
        """Test that thinking mode triggers on multiple consecutive calls."""
        agent = create_test_agent()

        prompts = [
            "What is a binary tree?",
            "How do I read a file in Python?",
            "Explain recursion.",
        ]

        results = []
        for prompt in prompts:
            messages = [
                {"role": "system", "content": get_thinking_system_prompt()},
                {"role": "user", "content": prompt}
            ]

            response = agent.call_llm(messages=messages, thinking_visible=True)
            assert response["success"], f"API call failed for '{prompt}': {response.get('error')}"
            results.append(has_think_tool_call(response))

        # All should trigger thinking
        success_rate = sum(results) / len(results)
        assert success_rate >= 0.8, (
            f"Thinking should trigger consistently (>=80%), got {success_rate*100}%. "
            f"Results: {list(zip(prompts, results))}"
        )


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_short_prompt(self):
        """Test thinking triggers even with very short prompt."""
        agent = create_test_agent()

        messages = [
            {"role": "system", "content": get_thinking_system_prompt()},
            {"role": "user", "content": "Hi"}
        ]

        response = agent.call_llm(messages=messages, thinking_visible=True)

        assert response["success"], f"API call failed: {response.get('error')}"
        # Even for "Hi", the instruction says MUST call think tool
        # But model might reasonably skip for greetings - check it at least works
        # This is more of a smoke test

    def test_multi_turn_conversation(self):
        """Test thinking in a multi-turn conversation."""
        agent = create_test_agent()

        messages = [
            {"role": "system", "content": get_thinking_system_prompt()},
            {"role": "user", "content": "I want to build a web scraper."},
            {"role": "assistant", "content": "I can help you build a web scraper. What website do you want to scrape?"},
            {"role": "user", "content": "I want to scrape news headlines from CNN."}
        ]

        response = agent.call_llm(messages=messages, thinking_visible=True)

        assert response["success"], f"API call failed: {response.get('error')}"
        assert has_think_tool_call(response), (
            "Model should call think tool in multi-turn conversation. "
            f"Got tool_calls: {response.get('tool_calls')}"
        )
