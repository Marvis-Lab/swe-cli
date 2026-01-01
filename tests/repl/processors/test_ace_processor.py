"""Tests for ACEProcessor."""

import unittest
from unittest.mock import MagicMock, patch, ANY
import pytest
from swecli.repl.processors.ace_processor import ACEProcessor
from swecli.core.context_engineering.memory import (
    Playbook,
    AgentResponse,
    ReflectorOutput,
    CuratorOutput,
    DeltaBatch,
    BulletTag
)

class TestACEProcessor:
    @pytest.fixture
    def mock_session_manager(self):
        return MagicMock()

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.get_playbook.return_value = MagicMock(spec=Playbook)
        return session

    @pytest.fixture
    def ace_processor(self, mock_session_manager):
        return ACEProcessor(mock_session_manager)

    @pytest.fixture
    def mock_agent(self):
        agent = MagicMock()
        agent.client = MagicMock()
        return agent

    def test_init(self, ace_processor, mock_session_manager):
        assert ace_processor.session_manager == mock_session_manager
        assert ace_processor._ace_reflector is None
        assert ace_processor._ace_curator is None
        assert ace_processor._last_agent_response is None
        assert ace_processor._execution_count == 0

    def test_set_last_agent_response(self, ace_processor):
        response = MagicMock(spec=AgentResponse)
        ace_processor.set_last_agent_response(response)
        assert ace_processor._last_agent_response == response

    def test_init_ace_components(self, ace_processor, mock_agent):
        ace_processor._init_ace_components(mock_agent)
        assert ace_processor._ace_reflector is not None
        assert ace_processor._ace_curator is not None

    def test_format_tool_feedback_success(self, ace_processor):
        tool_call1 = MagicMock()
        tool_call1.name = "tool1"
        tool_call1.error = None

        tool_call2 = MagicMock()
        tool_call2.name = "tool2"
        tool_call2.error = None

        feedback = ace_processor._format_tool_feedback([tool_call1, tool_call2], "success")

        assert "Outcome: success" in feedback
        assert "Tools executed: 2" in feedback
        assert "All tools completed successfully" in feedback
        assert "tool1, tool2" in feedback

    def test_format_tool_feedback_error(self, ace_processor):
        tool_call1 = MagicMock()
        tool_call1.name = "tool1"
        tool_call1.error = "Some error"

        feedback = ace_processor._format_tool_feedback([tool_call1], "error")

        assert "Outcome: error" in feedback
        assert "Errors (1):" in feedback
        assert "tool1: Some error" in feedback

    def test_format_tool_feedback_partial(self, ace_processor):
        tool_call1 = MagicMock()
        tool_call1.name = "tool1"
        tool_call1.error = None

        tool_call2 = MagicMock()
        tool_call2.name = "tool2"
        tool_call2.error = "Some error"

        feedback = ace_processor._format_tool_feedback([tool_call1, tool_call2], "partial")

        assert "Outcome: partial" in feedback
        assert "Partial success: 1/2 tools succeeded" in feedback

    @patch("swecli.repl.processors.ace_processor.Reflector")
    @patch("swecli.repl.processors.ace_processor.Curator")
    def test_record_tool_learnings(
        self,
        MockCurator,
        MockReflector,
        ace_processor,
        mock_session_manager,
        mock_session,
        mock_agent
    ):
        # Setup mocks
        mock_session_manager.current_session = mock_session
        playbook = mock_session.get_playbook.return_value
        playbook.bullets.return_value = []

        # Setup Reflector mock
        mock_reflector_instance = MockReflector.return_value
        reflection = MagicMock(spec=ReflectorOutput)
        reflection.bullet_tags = [
            MagicMock(id="1", tag="tag1")
        ]
        reflection.key_insight = "Insight"
        mock_reflector_instance.reflect.return_value = reflection

        # Setup Curator mock
        mock_curator_instance = MockCurator.return_value
        curator_output = MagicMock(spec=CuratorOutput)
        curator_output.delta = MagicMock(spec=DeltaBatch)
        curator_output.delta.operations = []
        curator_output.delta.reasoning = "Reasoning"
        mock_curator_instance.curate.return_value = curator_output

        # Setup agent response
        agent_response = MagicMock(spec=AgentResponse)
        ace_processor.set_last_agent_response(agent_response)

        # Setup tool calls
        tool_call = MagicMock()
        tool_call.name = "test_tool"
        tool_call.error = None
        tool_calls = [tool_call]

        # Call record_tool_learnings
        ace_processor.record_tool_learnings("query", tool_calls, "success", mock_agent)

        # Verify interactions
        mock_reflector_instance.reflect.assert_called_once()
        playbook.tag_bullet.assert_called_with("1", "tag1")
        mock_curator_instance.curate.assert_called_once()
        playbook.apply_delta.assert_called_with(curator_output.delta)
        mock_session.update_playbook.assert_called_with(playbook)

    def test_record_tool_learnings_no_session(self, ace_processor, mock_session_manager, mock_agent):
        mock_session_manager.current_session = None
        ace_processor.record_tool_learnings("query", [], "success", mock_agent)
        # Should return early without error
        assert ace_processor._execution_count == 0

    def test_record_tool_learnings_no_tool_calls(self, ace_processor, mock_session_manager, mock_session, mock_agent):
        mock_session_manager.current_session = mock_session
        ace_processor.record_tool_learnings("query", [], "success", mock_agent)
        # Should return early without error
        assert ace_processor._execution_count == 0

    def test_record_tool_learnings_no_agent_response(self, ace_processor, mock_session_manager, mock_session, mock_agent):
        mock_session_manager.current_session = mock_session
        ace_processor.record_tool_learnings("query", [MagicMock()], "success", mock_agent)
        # Should return early without error
        assert ace_processor._execution_count == 0
