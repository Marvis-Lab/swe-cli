"""Tests for ACEProcessor."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from swecli.repl.processors.ace_processor import ACEProcessor
from swecli.core.context_engineering.memory import AgentResponse

class TestACEProcessor:
    @pytest.fixture
    def mock_session_manager(self):
        return Mock()

    @pytest.fixture
    def ace_processor(self, mock_session_manager):
        return ACEProcessor(mock_session_manager)

    def test_init(self, ace_processor, mock_session_manager):
        assert ace_processor.session_manager == mock_session_manager
        assert ace_processor._ace_reflector is None
        assert ace_processor._ace_curator is None
        assert ace_processor._last_agent_response is None

    def test_init_ace_components(self, ace_processor):
        agent = Mock()
        ace_processor.init_ace_components(agent)
        assert ace_processor._ace_reflector is not None
        assert ace_processor._ace_curator is not None

    def test_set_last_agent_response(self, ace_processor):
        content = "Test content"
        tool_calls = [{"id": "1", "name": "test_tool"}]
        ace_processor.set_last_agent_response(content, tool_calls)
        assert ace_processor._last_agent_response is not None
        assert ace_processor._last_agent_response.content == content
        assert ace_processor._last_agent_response.tool_calls == tool_calls

    @patch("swecli.repl.processors.ace_processor.Reflector")
    @patch("swecli.repl.processors.ace_processor.Curator")
    def test_record_tool_learnings(self, mock_curator, mock_reflector, ace_processor, mock_session_manager):
        # Setup mocks
        session = Mock()
        mock_session_manager.current_session = session
        playbook = Mock()
        playbook.bullets.return_value = []  # Fix for len(playbook.bullets())
        session.get_playbook.return_value = playbook

        agent = Mock()
        tool_call = Mock()
        tool_call.name = "test_tool"
        tool_call.error = None
        tool_calls = [tool_call]

        reflection = Mock()
        bullet_tag = Mock()
        bullet_tag.id = "1"
        bullet_tag.tag = "test_tag"
        reflection.bullet_tags = [bullet_tag]

        mock_reflector_instance = Mock()
        mock_reflector_instance.reflect.return_value = reflection
        mock_reflector.return_value = mock_reflector_instance

        mock_curator_instance = Mock()
        curator_output = Mock()
        curator_output.delta.operations = []
        mock_curator_instance.curate.return_value = curator_output
        mock_curator.return_value = mock_curator_instance

        # When init_ace_components is called, it will overwrite the mocked instances if we are not careful
        # But we can just rely on the patches to return the right instances

        # Ensure that when Reflector() is called, it returns our mock instance
        mock_reflector.return_value = mock_reflector_instance
        # Ensure that when Curator() is called, it returns our mock instance
        mock_curator.return_value = mock_curator_instance

        # Important: set _ace_reflector and _ace_curator to None so init_ace_components creates them using our mocks
        ace_processor._ace_reflector = None
        ace_processor._ace_curator = None

        ace_processor.set_last_agent_response("content", [])

        # We need to make sure tool_calls is not empty, otherwise it returns early
        # Also need to make sure session is returned properly
        mock_session_manager.current_session = session

        ace_processor.record_tool_learnings("query", tool_calls, "success", agent)

        # Verify interactions
        mock_reflector_instance.reflect.assert_called_once()
        playbook.tag_bullet.assert_called_with("1", "test_tag")
        mock_curator_instance.curate.assert_called_once()
        playbook.apply_delta.assert_called_once()
        session.update_playbook.assert_called_once()
