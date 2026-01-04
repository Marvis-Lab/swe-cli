"""Tests for Context Preparer."""
from unittest.mock import MagicMock
import pytest

from swecli.repl.processors.context_preparer import ContextPreparer

class TestContextPreparer:
    @pytest.fixture
    def console(self):
        return MagicMock()

    @pytest.fixture
    def session_manager(self):
        return MagicMock()

    @pytest.fixture
    def config(self):
        return MagicMock()

    @pytest.fixture
    def file_ops(self):
        return MagicMock()

    @pytest.fixture
    def preparer(self, console, session_manager, config, file_ops):
        return ContextPreparer(console, session_manager, config, file_ops)

    def test_enhance_query_no_change(self, preparer):
        query = "hello world"
        assert preparer.enhance_query(query) == query

    def test_enhance_query_strip_at(self, preparer):
        query = "check @file.py"
        assert preparer.enhance_query(query) == "check file.py"

    def test_enhance_query_with_content(self, preparer, file_ops):
        file_ops.read_file.return_value = "content"
        query = "show me file.py"
        enhanced = preparer.enhance_query(query)

        assert "File contents of file.py" in enhanced
        assert "content" in enhanced
        file_ops.read_file.assert_called_with("file.py")

    def test_should_nudge_agent(self, preparer):
        messages = []
        # Less than 5 reads
        assert not preparer.should_nudge_agent(4, messages)
        assert len(messages) == 0

        # 5 reads
        assert preparer.should_nudge_agent(5, messages)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "summarize your findings" in messages[0]["content"]

    def test_should_attempt_error_recovery(self, preparer):
        # No attempts yet, last message is tool error
        messages = [{"role": "tool", "content": "Error: something failed"}]
        assert preparer.should_attempt_error_recovery(messages, 0)

        # Max attempts reached
        assert not preparer.should_attempt_error_recovery(messages, 3)

        # Last message is tool success
        messages = [{"role": "tool", "content": "success"}]
        assert not preparer.should_attempt_error_recovery(messages, 0)
