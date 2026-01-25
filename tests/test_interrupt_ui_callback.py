"""Test interrupt display via UI callback."""
from unittest.mock import Mock
from rich.text import Text
from swecli.ui_textual.ui_callback import TextualUICallback


def test_on_interrupt_calls_add_tool_result():
    """Test that on_interrupt uses _write_generic_tool_result - same as tool execution."""

    # Create mock conversation widget with lines array
    mock_conversation = Mock()
    mock_app = Mock()

    # Mock lines array with a blank line (simulating what add_user_message adds)
    mock_conversation.lines = [
        Text("› run @app.py", style="bold white"),
        Text(""),  # Blank line added by add_user_message
    ]

    # Track calls to _write_generic_tool_result
    calls = []
    def track_write_tool_result(text):
        calls.append(text)

    mock_conversation._write_generic_tool_result = track_write_tool_result
    mock_conversation.stop_spinner = Mock()

    # Track calls to _truncate_from
    truncate_calls = []
    def track_truncate(index):
        truncate_calls.append(index)

    mock_conversation._truncate_from = track_truncate

    # Create UI callback
    ui_callback = TextualUICallback(mock_conversation, mock_app)
    # _run_on_ui checks if self._app is not None, so it should be set
    # But in our test, we want direct execution, so we can mock call_from_thread
    ui_callback._app = None  # This will make _run_on_ui call func() directly

    # Call on_interrupt
    ui_callback.on_interrupt()

    # Verify the blank line was removed
    print("\n=== Test Results ===")
    print(f"Number of calls to _truncate_from: {len(truncate_calls)}")
    if truncate_calls:
        print(f"Truncated at index: {truncate_calls[0]}")
        assert len(truncate_calls) == 1, f"Expected 1 truncate call, got {len(truncate_calls)}"
        assert truncate_calls[0] == 1, f"Expected truncate at index 1 (to remove blank line), got {truncate_calls[0]}"
        print("✅ Blank line removed correctly")
    else:
        print("❌ Test FAILED - _truncate_from was not called")
        raise AssertionError("on_interrupt did not remove blank line")

    # Verify _write_generic_tool_result was called with interrupt marker
    print(f"Number of calls to _write_generic_tool_result: {len(calls)}")

    if calls:
        call_text = calls[0]
        print(f"Called with: {call_text}")

        # Assertions
        assert len(calls) == 1, f"Expected 1 call, got {len(calls)}"
        assert "::interrupted::" in call_text, "Expected ::interrupted:: marker"
        assert "Interrupted" in call_text, "Expected 'Interrupted' in message"
        assert "What should I do instead?" in call_text, "Expected 'What should I do instead?'"

        print("✅ Test PASSED - on_interrupt uses _write_generic_tool_result correctly")
    else:
        print("❌ Test FAILED - _write_generic_tool_result was not called")
        raise AssertionError("on_interrupt did not call _write_generic_tool_result")


if __name__ == "__main__":
    test_on_interrupt_calls_add_tool_result()
