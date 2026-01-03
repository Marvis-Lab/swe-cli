"""Tests for ContextPreparer."""

import pytest
from unittest.mock import Mock, patch
from swecli.repl.processors.context_preparer import ContextPreparer

class TestContextPreparer:
    @pytest.fixture
    def mock_console(self):
        return Mock()

    @pytest.fixture
    def mock_session_manager(self):
        return Mock()

    @pytest.fixture
    def mock_file_ops(self):
        return Mock()

    @pytest.fixture
    def mock_config(self):
        return Mock()

    @pytest.fixture
    def preparer(self, mock_console, mock_session_manager, mock_file_ops, mock_config):
        return ContextPreparer(mock_console, mock_session_manager, mock_file_ops, mock_config)

    def test_enhance_query_no_files(self, preparer):
        query = "How do I implement this?"
        enhanced = preparer.enhance_query(query)
        assert enhanced == query

    def test_enhance_query_with_at_ref(self, preparer):
        query = "Check @file.py"
        enhanced = preparer.enhance_query(query)
        assert enhanced == "Check file.py"

    def test_enhance_query_with_keywords_and_file(self, preparer, mock_file_ops):
        query = "Explain test.py"
        mock_file_ops.read_file.return_value = "content"
        enhanced = preparer.enhance_query(query)
        assert "File contents of test.py" in enhanced
        assert "content" in enhanced

    def test_prepare_messages_no_session(self, preparer, mock_session_manager):
        mock_session_manager.current_session = None
        agent = Mock()
        agent.system_prompt = "System prompt"

        messages = preparer.prepare_messages("query", "query", agent)

        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "System prompt"

    def test_prepare_messages_with_session(self, preparer, mock_session_manager):
        session = Mock()
        mock_session_manager.current_session = session
        session.to_api_messages.return_value = [{"role": "user", "content": "old"}]
        session.get_playbook.side_effect = Exception("No playbook") # Simple case

        agent = Mock()
        agent.system_prompt = "System prompt"

        messages = preparer.prepare_messages("query", "query", agent)

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
