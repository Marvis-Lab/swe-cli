#!/usr/bin/env python3
"""Test script to debug parallel tool display behavior.

This script simulates parallel tool calls to understand how spinners
and results are displayed.

Usage:
    python tests/manual/test_parallel_tools.py

This launches the Textual app and simulates parallel tool calls.
"""

import asyncio
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.text import Text
from rich.console import Console

# Mock conversation log for testing
class MockConversationLog:
    """Mock conversation log to test spinner behavior."""
    
    def __init__(self):
        self.lines = []
        self.output_buffer = []
        
    def write(self, text: Text | str, scroll_end: bool = True, animate: bool = False) -> None:
        """Write text to the log."""
        if isinstance(text, Text):
            plain = text.plain
        else:
            plain = str(text)
        self.lines.append(text)
        if plain.strip():
            self.output_buffer.append(plain)
        print(f"[LINE {len(self.lines):02d}] {plain}")
        
    def refresh_line(self, y: int) -> None:
        """Mock refresh."""
        pass
        
    def refresh(self) -> None:
        """Mock refresh."""
        pass


def test_parallel_spinners():
    """Test parallel spinner behavior directly."""
    print("=" * 60)
    print("Testing Parallel Spinner Behavior")
    print("=" * 60)
    
    # Import after path is set
    from swecli.ui_textual.managers.spinner_service import SpinnerService
    
    # Create mock app
    class MockApp:
        def __init__(self):
            self.conversation = MockConversationLog()
            self._loop = None
            
        def set_timer(self, interval, callback):
            """Mock timer - just return None (no animation in test)."""
            return None
            
        def call_from_thread(self, func, *args, **kwargs):
            """Call function directly."""
            return func(*args, **kwargs)
    
    mock_app = MockApp()
    
    # Create spinner service
    spinner_service = SpinnerService(mock_app)
    
    print("\n--- Starting Two Parallel Spinners ---\n")
    
    # Simulate parallel tool calls
    tool1_display = Text("Read ", style="bold white")
    tool1_display.append("(/Users/test/app.py)", style="dim")
    
    tool2_display = Text("Read ", style="bold white")
    tool2_display.append("(/Users/test/app_2.py)", style="dim")
    
    # Start both spinners
    spinner_id_1 = spinner_service.start(tool1_display)
    print(f"  → Spinner 1 ID: {spinner_id_1}")
    
    spinner_id_2 = spinner_service.start(tool2_display)
    print(f"  → Spinner 2 ID: {spinner_id_2}")
    
    # Verify each spinner has its own line
    print(f"\n--- Checking Spinner Line Tracking ---")
    print(f"  Spinner 1 line: {spinner_service._spinner_lines.get(spinner_id_1)}")
    print(f"  Spinner 2 line: {spinner_service._spinner_lines.get(spinner_id_2)}")
    
    line1 = spinner_service._spinner_lines.get(spinner_id_1)
    line2 = spinner_service._spinner_lines.get(spinner_id_2)
    
    if line1 is None or line2 is None:
        print("  ✗ FAIL: Spinners don't have tracked lines!")
        return False
        
    if line1 == line2:
        print("  ✗ FAIL: Both spinners share the same line!")
        return False
    
    print("  ✓ PASS: Each spinner has its own line")
    
    # Check result placeholders
    print(f"\n--- Checking Result Placeholders ---")
    result1 = spinner_service._result_lines.get(spinner_id_1)
    result2 = spinner_service._result_lines.get(spinner_id_2)
    print(f"  Spinner 1 result line: {result1}")
    print(f"  Spinner 2 result line: {result2}")
    
    if result1 is None or result2 is None:
        print("  ✗ FAIL: Result placeholders not tracked!")
        return False
        
    if result1 == result2:
        print("  ✗ FAIL: Both spinners share the same result line!")
        return False
    
    print("  ✓ PASS: Each spinner has its own result placeholder")
    
    # Stop spinners
    print(f"\n--- Stopping Spinners ---\n")
    
    spinner_service.stop(spinner_id_1, success=True, result_message="Read 34 lines • 840 B")
    print("  → Spinner 1 stopped")
    
    spinner_service.stop(spinner_id_2, success=True, result_message="Read 45 lines • 997 B")
    print("  → Spinner 2 stopped")
    
    print("\n" + "=" * 60)
    print("✓ All tests passed! Parallel spinners work correctly.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_parallel_spinners()
    sys.exit(0 if success else 1)
