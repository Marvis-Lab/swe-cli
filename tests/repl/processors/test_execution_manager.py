
import pytest
from unittest.mock import MagicMock, patch, ANY
from swecli.repl.processors.execution_manager import ExecutionManager
from swecli.core.runtime import OperationMode

class TestExecutionManager:
    @pytest.fixture
    def console(self):
        return MagicMock()

    @pytest.fixture
    def mode_manager(self):
        mm = MagicMock()
        mm.current_mode = OperationMode.NORMAL
        return mm

    @pytest.fixture
    def output_formatter(self):
        return MagicMock()

    @pytest.fixture
    def session_manager(self):
        return MagicMock()

    @pytest.fixture
    def manager(self, console, mode_manager, output_formatter, session_manager):
        return ExecutionManager(console, mode_manager, output_formatter, session_manager)

    def test_init(self, manager):
        assert manager.current_task_monitor is None
        assert manager.last_operation_summary == "—"
        assert manager.last_error is None

    @patch("swecli.repl.processors.execution_manager.TaskProgressDisplay")
    @patch("swecli.repl.processors.execution_manager.TaskMonitor")
    @patch("random.choice")
    @patch("time.sleep")
    def test_call_llm_with_progress(self, mock_sleep, mock_choice, mock_monitor_cls, mock_display_cls, manager):
        # Setup
        mock_choice.return_value = "Thinking"
        mock_monitor = mock_monitor_cls.return_value
        mock_display = mock_display_cls.return_value

        agent = MagicMock()
        agent.call_llm.return_value = {"success": True, "content": "Hello"}

        # Execute
        response, latency = manager.call_llm_with_progress(agent, [])

        # Verify
        assert response["content"] == "Hello"
        mock_monitor.start.assert_called()
        mock_display.start.assert_called()
        mock_display.stop.assert_called()
        agent.call_llm.assert_called()
        assert manager.current_task_monitor is None

    @patch("swecli.repl.processors.execution_manager.TaskProgressDisplay")
    @patch("swecli.repl.processors.execution_manager.TaskMonitor")
    def test_execute_tool_call(self, mock_monitor_cls, mock_display_cls, manager):
        # Setup
        mock_monitor = mock_monitor_cls.return_value
        mock_display = mock_display_cls.return_value

        tool_call = {
            "function": {
                "name": "test_tool",
                "arguments": '{"arg": "val"}'
            }
        }
        tool_registry = MagicMock()
        tool_registry.execute_tool.return_value = {"success": True, "output": "result"}

        approval_manager = MagicMock()
        undo_manager = MagicMock()

        # Execute
        result = manager.execute_tool_call(tool_call, tool_registry, approval_manager, undo_manager)

        # Verify
        assert result["success"] is True
        tool_registry.execute_tool.assert_called_with(
            "test_tool", {"arg": "val"},
            mode_manager=manager.mode_manager,
            approval_manager=approval_manager,
            undo_manager=undo_manager,
            task_monitor=mock_monitor,
            session_manager=manager.session_manager,
            ui_callback=None
        )
        assert manager.last_operation_summary != "—"
        assert manager.last_error is None
        mock_display.start.assert_called()
        mock_display.stop.assert_called()

    @patch("swecli.repl.processors.execution_manager.TaskProgressDisplay")
    def test_execute_tool_call_failure(self, mock_display_cls, manager):
        tool_call = {
            "function": {
                "name": "test_tool",
                "arguments": '{"arg": "val"}'
            }
        }
        tool_registry = MagicMock()
        tool_registry.execute_tool.return_value = {"success": False, "error": "Fail"}

        manager.execute_tool_call(tool_call, tool_registry, None, None)

        assert manager.last_error == "Fail"
