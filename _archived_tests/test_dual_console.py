#!/usr/bin/env python3
"""Test DualConsole functionality."""

import sys
from pathlib import Path
from io import StringIO

sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel
from swecli.ui.conversation_buffer import ConversationBuffer
from swecli.ui.dual_console import DualConsole


def test_dual_console():
    """Test DualConsole class."""
    print("Testing DualConsole...")

    # Test 1: Create dual console
    buffer = ConversationBuffer()
    # Use StringIO to capture console output for testing
    string_io = StringIO()
    console = Console(file=string_io, width=80)
    dual = DualConsole(console=console, buffer=buffer)

    assert dual.width == 80, "Width should match console"
    assert dual.buffer is buffer, "Buffer should be accessible"
    assert dual.console is console, "Console should be accessible"
    print("✓ DualConsole initialized correctly")

    # Test 2: Print text - should go to both console and buffer
    dual.print("Hello World")

    # Check console output
    console_output = string_io.getvalue()
    assert "Hello World" in console_output, "Text should be in console output"

    # Check buffer
    assert buffer.count() == 1, "Buffer should have 1 item"
    print("✓ print() outputs to both console and buffer")

    # Test 3: Print with style
    dual.print("Styled text", style="bold red")
    assert buffer.count() == 2, "Buffer should have 2 items"
    print("✓ print() with style works")

    # Test 4: Print Rich renderable (Panel)
    panel = Panel("Test Panel", title="Title")
    dual.print(panel)
    assert buffer.count() == 3, "Buffer should have 3 items"
    # The panel itself should be in the buffer
    items = buffer.get_all()
    assert items[2] is panel, "Panel should be stored directly in buffer"
    print("✓ print() with Rich renderables works")

    # Test 5: Disable capture
    dual.disable_buffer_capture()
    dual.print("This should not be captured")
    assert buffer.count() == 3, "Buffer should still have 3 items (capture disabled)"
    print("✓ disable_buffer_capture() works")

    # Test 6: Re-enable capture
    dual.enable_buffer_capture()
    dual.print("This should be captured")
    assert buffer.count() == 4, "Buffer should have 4 items (capture re-enabled)"
    print("✓ enable_buffer_capture() works")

    # Test 7: Clear buffer
    dual.clear_buffer()
    assert buffer.count() == 0, "Buffer should be empty after clear"
    print("✓ clear_buffer() works")

    # Test 8: Test as drop-in replacement (access console methods via delegation)
    # width/height should work
    assert hasattr(dual, 'width'), "Should have width property"
    assert hasattr(dual, 'height'), "Should have height property"

    # Other console attributes should be accessible via __getattr__
    assert hasattr(dual, 'file'), "Should delegate 'file' to console"
    print("✓ Acts as drop-in replacement for Console")

    # Test 9: Multiple objects in print
    dual.print("Item 1", "Item 2", "Item 3", sep=", ")
    assert buffer.count() == 1, "Should have 1 combined item"
    print("✓ print() with multiple objects works")

    print("\n✅ All tests passed! DualConsole is working correctly.")
    return True


if __name__ == "__main__":
    try:
        success = test_dual_console()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
