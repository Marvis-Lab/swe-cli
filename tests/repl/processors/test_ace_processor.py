"""Tests for ACE Processor."""
from unittest.mock import MagicMock, patch
import pytest

from swecli.repl.processors.ace_processor import ACEProcessor
from swecli.core.context_engineering.memory import AgentResponse

class TestACEProcessor:
    @pytest.fixture
    def session_manager(self):
        return MagicMock()

    @pytest.fixture
    def processor(self, session_manager):
        return ACEProcessor(session_manager)

    def test_init(self, processor, session_manager):
        assert processor.session_manager == session_manager
        assert processor._ace_reflector is None
        assert processor._ace_curator is None

    def test_set_last_agent_response(self, processor):
        content = "test content"
        tool_calls = [{"id": "1", "function": {"name": "test"}}]
        processor.set_last_agent_response(content, tool_calls)

        assert isinstance(processor._last_agent_response, AgentResponse)
        assert processor._last_agent_response.content == content
        assert processor._last_agent_response.tool_calls == tool_calls

    def test_format_tool_feedback_success(self, processor):
        tool_calls = [
            MagicMock(name="tool1", error=None),
            MagicMock(name="tool2", error=None)
        ]
        tool_calls[0].name = "tool1"
        tool_calls[1].name = "tool2"

        feedback = processor._format_tool_feedback(tool_calls, "success")

        assert "Outcome: success" in feedback
        assert "Tools executed: 2" in feedback
        assert "All tools completed successfully" in feedback
        assert "Tools: tool1, tool2" in feedback

    def test_format_tool_feedback_error(self, processor):
        tool_calls = [
            MagicMock(name="tool1", error="some error"),
        ]
        tool_calls[0].name = "tool1"

        feedback = processor._format_tool_feedback(tool_calls, "error")

        assert "Outcome: error" in feedback
        assert "Errors (1):" in feedback
        assert "- tool1: some error" in feedback
