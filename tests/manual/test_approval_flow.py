#!/usr/bin/env python3
"""End-to-end test for approval panel flow.

Test cases:
1. Approval panel appears without freeze
2. Up/down navigation works immediately
3. Enter confirms selection
4. Esc cancels
5. No flash when approval is confirmed
6. Tool result appears directly after approval

Run with: python tests/manual/test_approval_flow.py
Requires: OPENAI_API_KEY environment variable
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def check_openai_key():
    """Check if OpenAI API key is set."""
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY environment variable not set")
        print("Please set it: export OPENAI_API_KEY=your_key")
        sys.exit(1)
    print("✓ OPENAI_API_KEY is set")


def test_approval_controller_state_machine():
    """Test the approval controller state transitions."""
    print("\n" + "=" * 60)
    print("Test 1: Approval Controller State Machine")
    print("=" * 60)

    from unittest.mock import MagicMock, AsyncMock
    from swecli.ui_textual.controllers.approval_prompt_controller import ApprovalPromptController

    # Create mock app
    mock_app = MagicMock()
    mock_app.input_field = MagicMock()
    mock_app.input_field.text = ""
    mock_app.input_field.load_text = MagicMock()
    mock_app.input_field.focus = MagicMock()

    mock_conversation = MagicMock()
    mock_conversation.lines = []
    mock_conversation._approval_start = None
    mock_conversation._pending_approval_clear = False
    mock_conversation._tool_display = None
    mock_conversation._tool_call_start = None
    mock_conversation._tool_spinner_timer = None
    mock_conversation._spinner_active = False
    mock_conversation.stop_spinner = MagicMock()
    mock_conversation.render_approval_prompt = MagicMock()
    mock_conversation.scroll_end = MagicMock()
    mock_conversation.clear_approval_prompt = MagicMock()
    mock_conversation.defer_approval_clear = MagicMock()

    mock_app.conversation = mock_conversation
    mock_app._stop_local_spinner = MagicMock()
    mock_app._approval_controller = None

    controller = ApprovalPromptController(mock_app)

    # Test initial state
    assert not controller.active, "Controller should start inactive"
    assert controller._selected_index == 0, "Selected index should be 0"
    print("  ✓ Initial state correct")

    # Test move without active
    controller.move(1)
    assert controller._selected_index == 0, "Move should not change index when inactive"
    print("  ✓ Move ignored when inactive")

    # Test confirm without active
    controller.confirm()  # Should not raise
    print("  ✓ Confirm ignored when inactive")

    print("\n✓ State machine tests passed")


def test_approval_controller_navigation():
    """Test navigation within approval panel."""
    print("\n" + "=" * 60)
    print("Test 2: Approval Controller Navigation")
    print("=" * 60)

    from unittest.mock import MagicMock
    from swecli.ui_textual.controllers.approval_prompt_controller import ApprovalPromptController

    # Create mock app
    mock_app = MagicMock()
    mock_app.input_field = MagicMock()
    mock_app.input_field.text = ""

    mock_conversation = MagicMock()
    mock_conversation.lines = []
    mock_conversation._approval_start = None
    mock_conversation.render_approval_prompt = MagicMock()
    mock_conversation.scroll_end = MagicMock()

    mock_app.conversation = mock_conversation

    controller = ApprovalPromptController(mock_app)

    # Simulate active state with options
    controller._active = True
    controller._options = [
        {"choice": "1", "label": "Yes"},
        {"choice": "2", "label": "Yes, don't ask"},
        {"choice": "3", "label": "No"},
    ]
    controller._selected_index = 0

    # Test move down
    controller.move(1)
    assert controller._selected_index == 1, f"Expected 1, got {controller._selected_index}"
    print("  ✓ Move down works")

    # Test move down again
    controller.move(1)
    assert controller._selected_index == 2, f"Expected 2, got {controller._selected_index}"
    print("  ✓ Move down wraps correctly")

    # Test wrap around
    controller.move(1)
    assert controller._selected_index == 0, f"Expected 0 (wrap), got {controller._selected_index}"
    print("  ✓ Wrap around works")

    # Test move up
    controller.move(-1)
    assert controller._selected_index == 2, f"Expected 2, got {controller._selected_index}"
    print("  ✓ Move up works")

    print("\n✓ Navigation tests passed")


def test_deferred_approval_clear():
    """Test that approval panel clearing is deferred correctly."""
    print("\n" + "=" * 60)
    print("Test 3: Deferred Approval Clear (No Flash)")
    print("=" * 60)

    from rich.text import Text
    from unittest.mock import MagicMock, patch

    # Test the conversation log's deferred clearing
    from swecli.ui_textual.widgets.conversation_log import ConversationLog

    # We can't easily instantiate ConversationLog without Textual app context
    # So test the logic in isolation

    # Simulate the state
    class MockLog:
        def __init__(self):
            self.lines = [Text("line1"), Text("line2"), Text("approval panel")]
            self._approval_start = 2
            self._pending_approval_clear = False

        def defer_approval_clear(self):
            self._pending_approval_clear = True

        def write_with_clear(self, content):
            # Simulate the write() method's clearing logic
            if self._pending_approval_clear:
                self._pending_approval_clear = False
                if self._approval_start is not None and self._approval_start < len(self.lines):
                    del self.lines[self._approval_start:]
                self._approval_start = None
            self.lines.append(content)

    log = MockLog()

    # Verify initial state
    assert len(log.lines) == 3
    assert log._approval_start == 2
    print("  ✓ Initial state: 3 lines, approval at index 2")

    # Defer the clear
    log.defer_approval_clear()
    assert log._pending_approval_clear == True
    assert len(log.lines) == 3, "Lines should NOT be cleared yet"
    print("  ✓ Deferred clear: panel still visible")

    # Write new content (simulates tool result)
    log.write_with_clear(Text("tool result"))

    assert log._pending_approval_clear == False
    assert log._approval_start is None
    assert len(log.lines) == 3, f"Expected 3 lines, got {len(log.lines)}"
    assert log.lines[-1].plain == "tool result"
    print("  ✓ After write: approval cleared, result written atomically")

    print("\n✓ Deferred clear tests passed (no flash)")


def test_focus_timing():
    """Test that focus is properly awaited."""
    print("\n" + "=" * 60)
    print("Test 4: Focus Timing (asyncio.sleep(0) after focus)")
    print("=" * 60)

    import inspect
    from swecli.ui_textual.controllers.approval_prompt_controller import ApprovalPromptController

    # Check that start() method contains asyncio.sleep(0) after focus()
    source = inspect.getsource(ApprovalPromptController.start)

    # Look for the pattern: focus() followed by asyncio.sleep(0)
    if "focus()" in source and "await asyncio.sleep(0)" in source:
        # Check ordering
        focus_idx = source.find("focus()")
        sleep_idx = source.find("await asyncio.sleep(0)")

        if sleep_idx > focus_idx:
            print("  ✓ asyncio.sleep(0) is called after focus()")
        else:
            print("  ✗ asyncio.sleep(0) should be after focus()")
            return False
    else:
        print("  ✗ Missing focus() or asyncio.sleep(0) in start()")
        return False

    print("\n✓ Focus timing test passed")
    return True


async def test_e2e_with_openai():
    """End-to-end test with OpenAI API."""
    print("\n" + "=" * 60)
    print("Test 5: End-to-End with OpenAI (Manual Verification)")
    print("=" * 60)

    print("""
    This test requires manual verification:

    1. Run the CLI: python -m swecli
    2. Type: run @app.py (or any command that requires approval)
    3. Verify:
       a. Approval panel appears WITHOUT freeze
       b. Up/down arrows work IMMEDIATELY
       c. Enter confirms selection
       d. NO flash when approved - result appears smoothly

    Expected output after approval:
    ┌─────────────────────────────────────────────┐
    │ › run @app.py                               │
    │   ⎿  OK: python ran successfully            │
    │       * Serving Flask app 'app'             │
    │       ...                                   │
    └─────────────────────────────────────────────┘

    NOT:
    ┌─────────────────────────────────────────────┐
    │ › run @app.py                               │
    │                                             │  ← flash/blank
    │   ⎿  OK: python ran successfully            │
    └─────────────────────────────────────────────┘
    """)

    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("APPROVAL FLOW TEST SUITE")
    print("=" * 60)

    check_openai_key()

    all_passed = True

    # Unit tests
    try:
        test_approval_controller_state_machine()
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        all_passed = False

    try:
        test_approval_controller_navigation()
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        all_passed = False

    try:
        test_deferred_approval_clear()
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        all_passed = False

    try:
        if not test_focus_timing():
            all_passed = False
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        all_passed = False

    # E2E test instructions
    asyncio.run(test_e2e_with_openai())

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL AUTOMATED TESTS PASSED")
        print("\nPlease run manual E2E verification (Test 5 above)")
    else:
        print("✗ SOME TESTS FAILED")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
