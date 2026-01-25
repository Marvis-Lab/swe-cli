"""Tests for TextualUICallback threading behavior."""
from unittest.mock import Mock

from swecli.ui_textual.ui_callback import TextualUICallback

def test_run_on_ui_uses_threadsafe_when_loop_exists():
    """Test _run_on_ui uses call_soon_threadsafe when loop is available."""
    mock_app = Mock()
    mock_loop = Mock()
    mock_app._loop = mock_loop

    callback = TextualUICallback(Mock(), mock_app)
    func = Mock()

    callback._run_on_ui(func, 1, 2, key="value")

    mock_loop.call_soon_threadsafe.assert_called_once()
    # Check that the lambda passed to call_soon_threadsafe calls func with args
    call_args = mock_loop.call_soon_threadsafe.call_args[0]
    lambda_func = call_args[0]
    lambda_func()
    func.assert_called_with(1, 2, key="value")


def test_run_on_ui_uses_call_from_thread_when_loop_missing():
    """Test _run_on_ui falls back to call_from_thread when loop is missing."""
    mock_app = Mock()
    mock_app._loop = None

    callback = TextualUICallback(Mock(), mock_app)
    func = Mock()

    callback._run_on_ui(func, 1, 2, key="value")

    mock_app.call_from_thread.assert_called_once_with(func, 1, 2, key="value")


def test_progress_start_uses_blocking_call():
    """Test on_progress_start uses blocking call_from_thread."""
    mock_app = Mock()
    mock_conversation = Mock()

    callback = TextualUICallback(mock_conversation, mock_app)

    callback.on_progress_start("Working...")

    # Should call call_from_thread directly, not via _run_on_ui
    # (since _run_on_ui would prefer call_soon_threadsafe if loop existed)
    assert mock_app.call_from_thread.call_count >= 1

    # Verify it called add_tool_call
    calls = mock_app.call_from_thread.call_args_list

    # Should call both add_tool_call and start_tool_execution
    has_add_tool_call = any(
        call.args[0] == mock_conversation.add_tool_call for call in calls
    )
    has_start_tool = any(
        call.args[0] == mock_conversation.start_tool_execution for call in calls
    )

    assert has_add_tool_call
    assert has_start_tool


def test_tool_call_uses_blocking_call():
    """Test on_tool_call uses blocking call_from_thread."""
    mock_app = Mock()
    mock_conversation = Mock()

    callback = TextualUICallback(mock_conversation, mock_app)

    callback.on_tool_call("test_tool", {"arg": "val"})

    # Should call call_from_thread directly
    assert mock_app.call_from_thread.call_count >= 1

    # Verify it called add_tool_call
    calls = mock_app.call_from_thread.call_args_list

    has_add_tool_call = any(
        call.args[0] == mock_conversation.add_tool_call for call in calls
    )
    has_start_tool = any(
        call.args[0] == mock_conversation.start_tool_execution for call in calls
    )

    assert has_add_tool_call
    assert has_start_tool


def test_progress_complete_uses_non_blocking():
    """Test on_progress_complete uses _run_on_ui (non-blocking)."""
    mock_app = Mock()
    mock_loop = Mock()
    mock_app._loop = mock_loop

    mock_conversation = Mock()
    callback = TextualUICallback(mock_conversation, mock_app)

    callback.on_progress_complete("Done", success=True)

    # Should use call_soon_threadsafe via _run_on_ui
    assert mock_loop.call_soon_threadsafe.call_count >= 1
    # Should NOT use call_from_thread (blocking)
    assert mock_app.call_from_thread.call_count == 0
