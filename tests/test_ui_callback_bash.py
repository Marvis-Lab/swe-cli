"""Tests for bash command handling in TextualUICallback."""
from unittest.mock import Mock
from swecli.ui_textual.ui_callback import TextualUICallback


def test_bash_on_tool_call_does_not_show_header():
    """Test that on_tool_call for bash does NOT show header immediately.

    The header is shown by approval_manager._show_approval_modal() for commands
    that need approval, or by on_tool_result for auto-approved commands.
    """
    mock_app = Mock()
    mock_app._loop = None  # So _run_on_ui uses call_from_thread

    mock_conversation = Mock()
    callback = TextualUICallback(mock_conversation, mock_app)

    # Simulate tool call
    callback.on_tool_call("bash_execute", {"command": "echo hi"})

    # Verify add_tool_call was NOT called (header shown elsewhere)
    calls = mock_app.call_from_thread.call_args_list
    add_tool_call_calls = [c for c in calls if c.args[0] == mock_conversation.add_tool_call]
    assert len(add_tool_call_calls) == 0


def test_bash_tool_result_shows_header_if_not_shown():
    """Test that on_tool_result shows header for auto-approved commands."""
    mock_app = Mock()
    mock_app._loop = None
    mock_conversation = Mock()
    mock_conversation._current_tool_widget = None  # No header shown yet
    mock_conversation.add_bash_output_box = Mock()

    callback = TextualUICallback(mock_conversation, mock_app)

    # Tool finishes with output
    result = {"success": True, "output": "done"}
    callback.on_tool_result("bash_execute", {"command": "echo done"}, result)

    # Verify add_tool_call was called (since header wasn't shown before)
    calls = mock_app.call_from_thread.call_args_list
    add_tool_call_calls = [c for c in calls if c.args[0] == mock_conversation.add_tool_call]
    assert len(add_tool_call_calls) > 0

    # Verify stop_tool_execution was called
    stop_calls = [c for c in calls if c.args[0] == mock_conversation.stop_tool_execution]
    assert len(stop_calls) > 0


def test_bash_tool_result_skips_header_if_already_shown():
    """Test that on_tool_result doesn't duplicate header if already shown."""
    mock_app = Mock()
    mock_app._loop = None
    mock_conversation = Mock()
    mock_conversation._current_tool_widget = Mock()  # Header already shown
    mock_conversation.add_bash_output_box = Mock()

    callback = TextualUICallback(mock_conversation, mock_app)

    # Tool finishes with output
    result = {"success": True, "output": "done"}
    callback.on_tool_result("bash_execute", {"command": "echo done"}, result)

    # Verify add_tool_call was NOT called (header already shown)
    calls = mock_app.call_from_thread.call_args_list
    add_tool_call_calls = [c for c in calls if c.args[0] == mock_conversation.add_tool_call]
    assert len(add_tool_call_calls) == 0

    # Verify stop_tool_execution was called
    stop_calls = [c for c in calls if c.args[0] == mock_conversation.stop_tool_execution]
    assert len(stop_calls) > 0


def test_bash_tool_result_handles_error():
    """Test that on_tool_result handles errors correctly."""
    mock_app = Mock()
    mock_app._loop = None
    mock_conversation = Mock()
    mock_conversation._current_tool_widget = Mock()  # Header already shown
    mock_conversation.add_bash_output_box = Mock()

    callback = TextualUICallback(mock_conversation, mock_app)

    # Tool finishes with error
    result = {"success": False, "output": "command not found"}
    callback.on_tool_result("bash_execute", {"command": "badcmd"}, result)

    # Verify stop_tool_execution was called with success=False
    calls = mock_app.call_from_thread.call_args_list
    stop_calls = [c for c in calls if c.args[0] == mock_conversation.stop_tool_execution]
    assert len(stop_calls) > 0
    # The second argument should be False for error
    assert stop_calls[0].args[1] == False


def test_bash_tool_result_handles_interrupted():
    """Test that on_tool_result handles interrupted (approval denied) correctly."""
    mock_app = Mock()
    mock_app._loop = None
    mock_conversation = Mock()
    mock_conversation._current_tool_widget = Mock()  # Header was shown

    callback = TextualUICallback(mock_conversation, mock_app)

    # Tool was interrupted (approval denied)
    result = {"success": False, "interrupted": True}
    callback.on_tool_result("bash_execute", {"command": "rm -rf /"}, result)

    # Verify stop_tool_execution was called with success=False
    calls = mock_app.call_from_thread.call_args_list
    stop_calls = [c for c in calls if c.args[0] == mock_conversation.stop_tool_execution]
    assert len(stop_calls) > 0
    assert stop_calls[0].args[1] == False

    # Verify add_bash_output_box was NOT called (interrupted operations don't show output)
    box_calls = [c for c in calls if c.args[0] == mock_conversation.add_bash_output_box]
    assert len(box_calls) == 0


def test_bash_background_task_shows_message():
    """Test that background tasks show appropriate message."""
    mock_app = Mock()
    mock_app._loop = None
    mock_conversation = Mock()
    mock_conversation._current_tool_widget = Mock()  # Header was shown

    callback = TextualUICallback(mock_conversation, mock_app)

    # Background task result
    result = {"success": True, "background_task_id": "bg123"}
    callback.on_tool_result("bash_execute", {"command": "npm start"}, result)

    # Verify stop_tool_execution was called
    calls = mock_app.call_from_thread.call_args_list
    stop_calls = [c for c in calls if c.args[0] == mock_conversation.stop_tool_execution]
    assert len(stop_calls) > 0

    # Verify write was called (for background message)
    write_calls = [c for c in calls if c.args[0] == mock_conversation.write]
    assert len(write_calls) > 0
