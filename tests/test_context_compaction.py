"""Tests for context compaction feature."""

from unittest.mock import MagicMock


from swecli.core.context_engineering.compaction import ContextCompactor
from swecli.core.context_engineering.retrieval.token_monitor import ContextTokenMonitor
from swecli.models.config import AppConfig


def _make_compactor(max_context_tokens: int = 1000) -> ContextCompactor:
    """Create a ContextCompactor with a small context window for testing."""
    config = AppConfig()
    config.max_context_tokens = max_context_tokens
    config.model = "gpt-4"
    mock_client = MagicMock()
    return ContextCompactor(config, mock_client)


def _make_messages(count: int) -> list[dict]:
    """Generate a list of alternating user/assistant messages."""
    msgs = [{"role": "system", "content": "You are a helpful assistant."}]
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"Message {i}: {'x' * 200}"})
    return msgs


class TestContextCompactor:
    """Tests for ContextCompactor."""

    def test_should_compact_at_70_percent(self) -> None:
        """Should trigger at 70% of context window."""
        compactor = _make_compactor(max_context_tokens=100)
        # Many messages will definitely exceed 70 tokens
        messages = _make_messages(20)
        assert compactor.should_compact(messages, "System prompt")

    def test_should_not_compact_below_threshold(self) -> None:
        """Should NOT trigger below 70%."""
        compactor = _make_compactor(max_context_tokens=500_000)
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        assert not compactor.should_compact(messages, "System prompt")

    def test_preserves_system_prompt(self) -> None:
        """First message (system) should always be preserved."""
        compactor = _make_compactor(max_context_tokens=100)
        messages = _make_messages(20)
        result = compactor.compact(messages, "System prompt")
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a helpful assistant."

    def test_preserves_recent_messages(self) -> None:
        """Last N messages should remain intact."""
        compactor = _make_compactor(max_context_tokens=100)
        messages = _make_messages(30)
        result = compactor.compact(messages, "System prompt")
        # Recent messages should be preserved exactly
        assert result[-1] == messages[-1]
        assert result[-2] == messages[-2]

    def test_summarizes_middle_messages(self) -> None:
        """Messages between system and recent should be summarized."""
        compactor = _make_compactor(max_context_tokens=100)
        messages = _make_messages(20)
        result = compactor.compact(messages, "System prompt")
        # Should have: system + summary + recent messages
        assert len(result) < len(messages)
        # Second message should be the summary
        assert "CONVERSATION SUMMARY" in result[1]["content"]

    def test_summary_replaces_old_messages(self) -> None:
        """After compaction, old messages replaced with summary."""
        compactor = _make_compactor(max_context_tokens=100)
        messages = _make_messages(20)
        original_count = len(messages)
        result = compactor.compact(messages, "System prompt")
        assert len(result) < original_count

    def test_handles_minimal_messages(self) -> None:
        """Should not crash on minimal message history."""
        compactor = _make_compactor(max_context_tokens=100)
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hi"},
        ]
        result = compactor.compact(messages, "System")
        # Too few messages to compact — should return as-is
        assert result == messages

    def test_handles_empty_messages(self) -> None:
        """Should handle empty message list gracefully."""
        compactor = _make_compactor(max_context_tokens=100)
        result = compactor.compact([], "System")
        assert result == []


class TestTokenCounting:
    """Tests for ContextTokenMonitor."""

    def test_token_counting_works(self) -> None:
        """Token counting should return positive values."""
        monitor = ContextTokenMonitor(model="gpt-4")
        count = monitor.count_tokens("Hello, world! This is a test.")
        assert count > 0

    def test_empty_string(self) -> None:
        """Empty string should return 0 tokens."""
        monitor = ContextTokenMonitor(model="gpt-4")
        assert monitor.count_tokens("") == 0
