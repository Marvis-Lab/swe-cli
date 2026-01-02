
import pytest
from unittest.mock import MagicMock, patch, ANY
from swecli.repl.processors.ace_processor import ACEProcessor
from swecli.core.context_engineering.memory import AgentResponse
from swecli.models.message import ToolCall

class TestACEProcessor:
    @pytest.fixture
    def session_manager(self):
        return MagicMock()

    @pytest.fixture
    def processor(self, session_manager):
        return ACEProcessor(session_manager)

    @pytest.fixture
    def mock_agent(self):
        agent = MagicMock()
        agent.client = MagicMock()
        return agent

    def test_init_components(self, processor, mock_agent):
        assert processor._ace_reflector is None
        assert processor._ace_curator is None

        processor.init_components(mock_agent)

        assert processor._ace_reflector is not None
        assert processor._ace_curator is not None

    def test_set_last_agent_response(self, processor):
        response = AgentResponse(content="test", tool_calls=[])
        processor.set_last_agent_response(response)
        assert processor._last_agent_response == response

    def test_record_tool_learnings_no_session(self, processor, mock_agent):
        processor.session_manager.current_session = None
        # Should not raise
        processor.record_tool_learnings("query", [], "success", mock_agent)

    def test_record_tool_learnings_no_tool_calls(self, processor, mock_agent):
        processor.session_manager.current_session = MagicMock()
        # Should not raise
        processor.record_tool_learnings("query", [], "success", mock_agent)

    def test_record_tool_learnings_no_agent_response(self, processor, mock_agent):
        processor.session_manager.current_session = MagicMock()
        tool_call = ToolCall(
            id="1", name="tool", parameters={},
            result="res", result_summary="res", error=None, approved=True
        )
        processor.record_tool_learnings("query", [tool_call], "success", mock_agent)

    @patch("swecli.repl.processors.ace_processor.Reflector")
    @patch("swecli.repl.processors.ace_processor.Curator")
    def test_record_tool_learnings_flow(self, mock_curator_cls, mock_reflector_cls, processor, mock_agent):
        # Setup mocks
        session = MagicMock()
        playbook = MagicMock()
        session.get_playbook.return_value = playbook
        processor.session_manager.current_session = session

        mock_reflector = mock_reflector_cls.return_value
        mock_curator = mock_curator_cls.return_value

        reflection = MagicMock()
        reflection.bullet_tags = []
        mock_reflector.reflect.return_value = reflection

        curator_output = MagicMock()
        curator_output.delta.operations = []
        mock_curator.curate.return_value = curator_output

        # Setup data
        agent_response = AgentResponse(content="test", tool_calls=[])
        processor.set_last_agent_response(agent_response)

        tool_call = ToolCall(
            id="1", name="tool", parameters={},
            result="res", result_summary="res", error=None, approved=True
        )

        # Execute
        processor.record_tool_learnings("query", [tool_call], "success", mock_agent)

        # Verify interactions
        mock_reflector.reflect.assert_called_once()
        mock_curator.curate.assert_called_once()
        playbook.apply_delta.assert_called_once()
        session.update_playbook.assert_called_once_with(playbook)

    def test_format_tool_feedback_success(self, processor):
        tool_call = ToolCall(
            id="1", name="tool1", parameters={},
            result="res", result_summary="res", error=None, approved=True
        )
        feedback = processor._format_tool_feedback([tool_call], "success")
        assert "Outcome: success" in feedback
        assert "Tools executed: 1" in feedback
        assert "tool1" in feedback

    def test_format_tool_feedback_error(self, processor):
        tool_call = ToolCall(
            id="1", name="tool1", parameters={},
            result=None, result_summary=None, error="Some error", approved=True
        )
        feedback = processor._format_tool_feedback([tool_call], "error")
        assert "Outcome: error" in feedback
        assert "Errors (1):" in feedback
        assert "Some error" in feedback
