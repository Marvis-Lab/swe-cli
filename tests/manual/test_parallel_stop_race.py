#!/usr/bin/env python3
"""Test that parallel spinner stop operations don't cause race conditions.

This tests the fix for duplicate lines appearing when multiple parallel tools
stop at nearly the same time.
"""

import sys
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.text import Text


def test_parallel_stop_race():
    """Test that stopping spinners in parallel doesn't cause race conditions."""
    print("=" * 60)
    print("Testing Parallel Stop Race Condition Fix")
    print("=" * 60)

    from swecli.ui_textual.managers.spinner_service import SpinnerService

    # Track lines written and their content
    write_log = []
    line_updates = []  # Track in-place line updates

    class MockConversationLog:
        def __init__(self):
            self.lines = []
            self._pending_spacing_line = None

        def write(self, text, scroll_end=True, animate=False):
            self.lines.append(text)
            plain = text.plain if hasattr(text, 'plain') else str(text)
            write_log.append(plain)
            if plain.strip():
                print(f"  [WRITE] Line {len(self.lines)-1}: {plain}")

        def refresh_line(self, y):
            pass

        def refresh(self):
            pass

        def set_timer(self, interval, callback):
            return MockTimer(interval, callback)

    class MockTimer:
        def __init__(self, interval, callback):
            self._callback = callback
            self._interval = interval
            self._stopped = False
            self._timer = None
            self._fire()

        def _fire(self):
            if self._stopped:
                return
            self._timer = threading.Timer(self._interval, self._on_fire)
            self._timer.daemon = True
            self._timer.start()

        def _on_fire(self):
            if not self._stopped:
                self._callback()

        def stop(self):
            self._stopped = True
            if self._timer:
                self._timer.cancel()

    class MockApp:
        def __init__(self):
            self.conversation = MockConversationLog()
            self._loop = None

        def set_timer(self, interval, callback):
            return MockTimer(interval, callback)

        def call_from_thread(self, func, *args, **kwargs):
            return func(*args, **kwargs)

        def refresh(self):
            pass

    mock_app = MockApp()
    spinner_service = SpinnerService(mock_app)

    print("\n--- Starting 2 Parallel Spinners ---")

    tool1_display = Text("Read ")
    tool1_display.append("(/Users/test/app.py)")

    tool2_display = Text("Read ")
    tool2_display.append("(/Users/test/app_2.py)")

    spinner_id_1 = spinner_service.start(tool1_display)
    spinner_id_2 = spinner_service.start(tool2_display)

    print(f"\n  Spinner 1 ID: {spinner_id_1}, line: {spinner_service._spinner_lines.get(spinner_id_1)}")
    print(f"  Spinner 2 ID: {spinner_id_2}, line: {spinner_service._spinner_lines.get(spinner_id_2)}")
    print(f"  Total lines after start: {len(mock_app.conversation.lines)}")

    # Let animation run briefly
    time.sleep(0.3)

    print("\n--- Stopping Both Spinners in Parallel (simulating ThreadPoolExecutor) ---")

    # This simulates what happens when two parallel tool calls complete
    # and both call stop() nearly simultaneously
    stop_order = []

    def stop_spinner_1():
        stop_order.append("1_start")
        spinner_service.stop(spinner_id_1, success=True, result_message="Read 34 lines")
        stop_order.append("1_end")

    def stop_spinner_2():
        stop_order.append("2_start")
        spinner_service.stop(spinner_id_2, success=True, result_message="Read 45 lines")
        stop_order.append("2_end")

    # Execute stops in parallel threads (like ThreadPoolExecutor would)
    t1 = threading.Thread(target=stop_spinner_1)
    t2 = threading.Thread(target=stop_spinner_2)

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    print(f"\n  Stop order: {stop_order}")
    print(f"  Total lines after stop: {len(mock_app.conversation.lines)}")

    # Check that we have the expected number of lines:
    # For each tool: 1 spinner line + 1 result placeholder + 1 spacing placeholder = 3 lines
    # Total: 6 lines for 2 tools
    expected_lines = 6  # 2 tools * 3 lines each

    print("\n--- Verifying Line Content ---")

    def get_plain_text(line):
        """Extract plain text from Strip or Text object."""
        if hasattr(line, 'plain'):
            return line.plain
        # Strip objects have _segments
        if hasattr(line, '_segments'):
            return ''.join(seg.text for seg in line._segments)
        return str(line)

    for i, line in enumerate(mock_app.conversation.lines):
        plain = get_plain_text(line)
        print(f"  Line {i}: {plain}")

    # Check for duplicates - count lines containing each file path
    lines_with_app_py = sum(1 for line in mock_app.conversation.lines
                           if 'app.py' in get_plain_text(line) and 'app_2' not in get_plain_text(line))
    lines_with_app_2_py = sum(1 for line in mock_app.conversation.lines
                              if 'app_2.py' in get_plain_text(line))

    print(f"\n  Lines containing 'app.py' (not app_2): {lines_with_app_py}")
    print(f"  Lines containing 'app_2.py': {lines_with_app_2_py}")

    # Each tool should appear exactly once in the lines (the spinner line)
    # The animation might have updated the line in-place, but there should be no duplicates
    if lines_with_app_py == 1 and lines_with_app_2_py == 1:
        print("\n" + "=" * 60)
        print("✓ PASS: No duplicate lines! Race condition fix verified.")
        print("=" * 60)
        return True
    else:
        print("\n" + "=" * 60)
        print("✗ FAIL: Duplicate lines detected!")
        print(f"  Expected 1 line each for app.py and app_2.py")
        print("=" * 60)
        return False


if __name__ == "__main__":
    success = test_parallel_stop_race()
    sys.exit(0 if success else 1)
