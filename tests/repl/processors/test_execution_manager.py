"""Tests for ExecutionManager."""

import pytest
from unittest.mock import Mock, patch
from swecli.repl.processors.execution_manager import ExecutionManager

class TestExecutionManager:
    @pytest.fixture
    def mock_console(self):
        return Mock()

    @pytest.fixture
    def mock_session_manager(self):
        return Mock()

    @pytest.fixture
    def mock_mode_manager(self):
        return Mock()

    @pytest.fixture
    def mock_output_formatter(self):
        return Mock()

    @pytest.fixture
    def manager(self, mock_console, mock_session_manager, mock_mode_manager, mock_output_formatter):
        return ExecutionManager(mock_console, mock_session_manager, mock_mode_manager, mock_output_formatter)

    def test_should_nudge_agent(self, manager):
        messages = []
        assert not manager.should_nudge_agent(4, messages)
        assert len(messages) == 0

        assert manager.should_nudge_agent(5, messages)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_should_attempt_error_recovery(self, manager):
        messages = [{"role": "tool", "content": "Error: failed"}]
        assert manager.should_attempt_error_recovery(messages, 0)
        assert not manager.should_attempt_error_recovery(messages, 3) # Max attempts

        messages = [{"role": "tool", "content": "Success"}]
        assert not manager.should_attempt_error_recovery(messages, 0)

    @patch("swecli.ui_textual.components.task_progress.TaskProgressDisplay")
    def test_call_llm_with_progress(self, mock_progress, manager):
        agent = Mock()
        agent.call_llm.return_value = {"content": "response"}
        task_monitor = Mock()

        response, latency = manager.call_llm_with_progress(agent, [], task_monitor)

        assert response["content"] == "response"
        assert isinstance(latency, int)
        task_monitor.start.assert_called_once()
