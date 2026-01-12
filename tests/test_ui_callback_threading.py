"""Tests for TextualUICallback threading behavior."""
from unittest.mock import Mock
from swecli.ui_textual.ui_callback import TextualUICallback


def test_run_on_ui_uses_call_from_thread():
    """Test _run_on_ui uses call_from_thread for synchronous UI updates."""
    mock_app = Mock()
    mock_app._loop = None  # Loop doesn't affect behavior

    callback = TextualUICallback(Mock(), mock_app)
    func = Mock()

    callback._run_on_ui(func, 1, 2, key="value")

    mock_app.call_from_thread.assert_called_once_with(func, 1, 2, key="value")


def test_run_on_ui_direct_call_when_no_app():
    """Test _run_on_ui calls function directly when no app available."""
    callback = TextualUICallback(Mock(), None)
    func = Mock()

    callback._run_on_ui(func, 1, 2, key="value")

    func.assert_called_once_with(1, 2, key="value")


def test_tool_call_no_header_for_bash():
    """Test on_tool_call does NOT show header for bash commands.

    Headers for bash commands are shown by:
    - approval_manager._show_approval_modal() for commands needing approval
    - on_tool_result for auto-approved commands
    """
    mock_app = Mock()
    mock_app._loop = None
    mock_conversation = Mock()

    callback = TextualUICallback(mock_conversation, mock_app)

    callback.on_tool_call("bash_execute", {"command": "echo hello"})

    # Should NOT call add_tool_call for bash
    calls = mock_app.call_from_thread.call_args_list

    has_add_tool_call = any(
        call.args[0] == mock_conversation.add_tool_call for call in calls
    )

    assert not has_add_tool_call


def test_tool_call_shows_header_for_spawn_subagent():
    """Test on_tool_call shows header immediately for spawn_subagent."""
    mock_app = Mock()
    mock_app._loop = None
    mock_conversation = Mock()

    callback = TextualUICallback(mock_conversation, mock_app)

    callback.on_tool_call("spawn_subagent", {"task": "do something"})

    # Should call call_from_thread
    calls = mock_app.call_from_thread.call_args_list

    # Should call add_tool_call and start_tool_execution
    has_add_tool_call = any(
        call.args[0] == mock_conversation.add_tool_call for call in calls
    )
    has_start_tool = any(
        call.args[0] == mock_conversation.start_tool_execution for call in calls
    )

    assert has_add_tool_call
    assert has_start_tool


def test_tool_call_no_header_for_other_tools():
    """Test on_tool_call does NOT show header for other tools (shown in on_tool_result)."""
    mock_app = Mock()
    mock_app._loop = None
    mock_conversation = Mock()

    callback = TextualUICallback(mock_conversation, mock_app)

    callback.on_tool_call("read_file", {"path": "/tmp/file.txt"})

    # Should NOT call add_tool_call for read_file
    calls = mock_app.call_from_thread.call_args_list

    has_add_tool_call = any(
        call.args[0] == mock_conversation.add_tool_call for call in calls
    )

    assert not has_add_tool_call


def test_tool_call_stops_spinner_for_think_tool():
    """Test on_tool_call stops spinner for think tool."""
    mock_app = Mock()
    mock_app._loop = None
    mock_app._stop_local_spinner = Mock()
    mock_conversation = Mock()

    callback = TextualUICallback(mock_conversation, mock_app)

    callback.on_tool_call("think", {"thought": "thinking..."})

    # Should call _stop_local_spinner
    calls = mock_app.call_from_thread.call_args_list

    has_stop_spinner = any(
        call.args[0] == mock_app._stop_local_spinner for call in calls
    )

    assert has_stop_spinner
