"""Tests for bash streaming logic in TextualUICallback."""
from unittest.mock import Mock
from swecli.ui_textual.ui_callback import TextualUICallback

def test_bash_output_triggers_lazy_start():
    """Test that on_bash_output_line triggers box start only when output arrives."""
    mock_app = Mock()
    # No loop, so _run_on_ui calls call_from_thread
    mock_app._loop = None

    mock_conversation = Mock()
    callback = TextualUICallback(mock_conversation, mock_app)

    # Simulate tool call (sets up pending state)
    callback.on_tool_call("bash_execute", {"command": "echo hi"})

    assert callback._pending_bash_start is True
    assert callback._streaming_bash_box is False
    assert callback._pending_bash_command == "echo hi"

    # Trigger output
    callback.on_bash_output_line("line 1")

    # Should have triggered start
    assert callback._pending_bash_start is False
    assert callback._streaming_bash_box is True

    # Manually flush the buffer to ensure append is called
    callback._flush_bash_buffer()

    # Verify calls
    # 1. start_streaming_bash_box
    # 2. append_to_streaming_box
    calls = mock_app.call_from_thread.call_args_list

    any(c.args[0] == mock_conversation.start_streaming_bash_box for c in calls)

    # Check if update_ui wrapper called append_to_streaming_box
    # Since _run_on_ui wraps the call, we need to inspect what was passed to call_from_thread
    # or rely on checking if the update_ui function was passed and execute it if needed.
    # However, since we mock call_from_thread, we can check if it was called with a function that
    # eventually calls append_to_streaming_box.

    # But since _run_on_ui calls `func(*args, **kwargs)`, and `func` is `update_ui`
    # and args is `chunk`, we can check if `update_ui` was passed.

    # Actually, let's verify that call_from_thread was called with SOMETHING.
    # The actual append_to_streaming_box call happens INSIDE the function passed to call_from_thread.
    # So we can't easily assert that mock_conversation.append_to_streaming_box was called directly
    # unless we execute the callback.

    # Let's find the call that corresponds to _flush_bash_buffer's _run_on_ui
    # It passes (update_ui, chunk)

    flush_calls = [c for c in calls if c.args and callable(c.args[0]) and getattr(c.args[0], "__name__", "") == 'update_ui']
    assert len(flush_calls) > 0

    # Execute the callback to verify it calls append_to_streaming_box
    update_ui_func = flush_calls[0].args[0]
    chunk = flush_calls[0].args[1]
    update_ui_func(chunk)

    assert mock_conversation.append_to_streaming_box.called

def test_bash_tool_result_closes_box():
    """Test that on_tool_result closes the streaming box."""
    mock_app = Mock()
    mock_app._loop = None
    mock_conversation = Mock()

    callback = TextualUICallback(mock_conversation, mock_app)

    # Setup streaming state manually
    callback._streaming_bash_box = True
    callback._pending_bash_start = False

    # Tool finishes
    result = {"success": True, "output": "done"}
    callback.on_tool_result("bash_execute", {}, result)

    assert callback._streaming_bash_box is False

    # Verify close call
    calls = mock_app.call_from_thread.call_args_list
    has_close = any(c.args[0] == mock_conversation.close_streaming_bash_box for c in calls)
    assert has_close

def test_bash_tool_result_fallback_box():
    """Test that if no streaming happened (no output), a static box is added."""
    mock_app = Mock()
    mock_app._loop = None
    mock_conversation = Mock()

    callback = TextualUICallback(mock_conversation, mock_app)

    # No streaming happened
    callback._streaming_bash_box = False
    callback._pending_bash_start = False # Reset by on_tool_result anyway

    # Tool finishes with output
    result = {"success": True, "stdout": "result"}
    callback.on_tool_result("bash_execute", {"command": "cmd"}, result)

    # Should add static bash box
    calls = mock_app.call_from_thread.call_args_list
    has_add_box = any(c.args[0] == mock_conversation.add_bash_output_box for c in calls)
    assert has_add_box
