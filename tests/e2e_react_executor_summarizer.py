"""E2E test for conversation summarizer integration with ReactExecutor.

Tests the full integration path: ReactExecutor -> ConversationSummarizer -> LLM
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
from swecli.repl.react_executor import ReactExecutor, SHORT_TERM_PAIRS


def test_react_executor_summarizer_integration():
    """Test that ReactExecutor correctly uses the summarizer."""
    print("\n" + "=" * 60)
    print("E2E TEST: ReactExecutor Summarizer Integration")
    print("=" * 60)

    # Create executor with mocked dependencies
    executor = ReactExecutor(
        console=MagicMock(),
        session_manager=MagicMock(),
        config=MagicMock(),
        llm_caller=MagicMock(),
        tool_executor=MagicMock(),
    )

    # Check summarizer is initialized
    assert executor._conversation_summarizer is not None
    print("✓ Summarizer initialized in ReactExecutor")

    # Check summarizer config
    assert executor._conversation_summarizer._regenerate_threshold == 5
    print(f"✓ Regenerate threshold: {executor._conversation_summarizer._regenerate_threshold}")

    # Check SHORT_TERM_PAIRS constant
    print(f"✓ SHORT_TERM_PAIRS: {SHORT_TERM_PAIRS}")
    print(f"✓ Summarization triggers when message_count > {SHORT_TERM_PAIRS * 3}")

    # Test needs_regeneration logic
    summarizer = executor._conversation_summarizer

    # No cache = needs regeneration
    assert summarizer.needs_regeneration(10) is True
    print("✓ needs_regeneration returns True when no cache")

    # Simulate having a cache
    from swecli.core.context_engineering.memory.conversation_summarizer import ConversationSummary
    summarizer._cache = ConversationSummary(
        summary="Test summary",
        message_count=10,
        last_summarized_index=8,
    )

    # Below threshold
    assert summarizer.needs_regeneration(14) is False
    print("✓ needs_regeneration returns False below threshold")

    # At threshold
    assert summarizer.needs_regeneration(15) is True
    print("✓ needs_regeneration returns True at threshold")

    print("\n" + "=" * 60)
    print("INTEGRATION TEST PASSED ✓")
    print("=" * 60)


def test_get_thinking_trace_uses_summarizer():
    """Test that _get_thinking_trace correctly integrates with summarizer."""
    print("\n" + "=" * 60)
    print("E2E TEST: _get_thinking_trace Integration")
    print("=" * 60)

    executor = ReactExecutor(
        console=MagicMock(),
        session_manager=MagicMock(),
        config=MagicMock(),
        llm_caller=MagicMock(),
        tool_executor=MagicMock(),
    )

    # Create enough messages to trigger summarization
    # Need > SHORT_TERM_PAIRS * 3 = 9 non-system messages
    messages = [{"role": "system", "content": "You are helpful."}]
    for i in range(6):  # 12 messages = 6 pairs
        messages.append({"role": "user", "content": f"Question {i+1}"})
        messages.append({"role": "assistant", "content": f"Answer {i+1}"})

    print(f"Created {len(messages)} messages ({len(messages)-1} non-system)")

    # Track summarizer calls
    summarizer_calls = []
    original_generate = executor._conversation_summarizer.generate_summary

    def track_generate(msgs, llm_caller):
        summarizer_calls.append({"msg_count": len(msgs)})
        return "Mock conversation summary for testing"

    executor._conversation_summarizer.generate_summary = track_generate

    # Mock the agent
    mock_agent = MagicMock()
    thinking_llm_calls = []

    def capture_thinking_call(msgs, monitor):
        thinking_llm_calls.append(msgs)
        return {"success": True, "content": "I should analyze the user's question..."}

    mock_agent.call_thinking_llm = capture_thinking_call
    mock_agent.build_system_prompt = MagicMock(return_value="System prompt with context:\n{context}")

    # Call _get_thinking_trace
    result = executor._get_thinking_trace(messages, mock_agent, ui_callback=None)

    print(f"Summarizer calls: {len(summarizer_calls)}")
    print(f"Thinking LLM calls: {len(thinking_llm_calls)}")

    # Verify summarizer was called
    assert len(summarizer_calls) == 1, "Summarizer should be called once"
    print("✓ Summarizer was called during thinking phase")

    # Verify the thinking LLM received the context
    if thinking_llm_calls:
        system_msg = thinking_llm_calls[0][0]["content"]
        has_summary_header = "CONVERSATION SUMMARY (episodic memory)" in system_msg
        has_summary_content = "Mock conversation summary" in system_msg
        print(f"✓ Summary header in prompt: {has_summary_header}")
        print(f"✓ Summary content in prompt: {has_summary_content}")
        assert has_summary_header, "Summary header should be in thinking system prompt"
        assert has_summary_content, "Summary content should be in thinking system prompt"

    print(f"✓ Thinking trace result: {result[:50]}...")

    print("\n" + "=" * 60)
    print("_get_thinking_trace TEST PASSED ✓")
    print("=" * 60)


if __name__ == "__main__":
    test_react_executor_summarizer_integration()
    test_get_thinking_trace_uses_summarizer()

    print("\n" + "=" * 60)
    print("ALL INTEGRATION TESTS PASSED ✓")
    print("=" * 60)
