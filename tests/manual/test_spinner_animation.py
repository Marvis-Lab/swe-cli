#!/usr/bin/env python3
"""Test script to debug spinner animation during parallel tool execution.

Tests whether the animation loop actually fires ticks during execution.
"""

import sys
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.text import Text

# Track animation ticks
tick_log = []
original_on_tick = None


def test_spinner_animation():
    """Test spinner animation fires during simulated tool execution."""
    print("=" * 60)
    print("Testing Spinner Animation During Parallel Tool Execution")
    print("=" * 60)
    
    from swecli.ui_textual.managers.spinner_service import SpinnerService
    
    # Track render callbacks
    render_count = {"spinner1": 0, "spinner2": 0}
    
    class MockConversationLog:
        def __init__(self):
            self.lines = []
            
        def write(self, text, scroll_end=True, animate=False):
            self.lines.append(text)
            plain = text.plain if hasattr(text, 'plain') else str(text)
            if plain.strip():
                print(f"  [WRITE] {plain}")
                
        def refresh_line(self, y):
            pass
            
        def refresh(self):
            pass
            
        def set_timer(self, interval, callback):
            """Mock timer that actually fires."""
            return MockTimer(interval, callback)
    
    class MockTimer:
        def __init__(self, interval, callback):
            self._callback = callback
            self._interval = interval
            self._stopped = False
            self._timer = None
            # Start a thread that fires the callback
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
            # Call directly (simulate being on UI thread)
            return func(*args, **kwargs)
    
    mock_app = MockApp()
    spinner_service = SpinnerService(mock_app)
    
    # Patch render_frame to count calls
    original_render = spinner_service._render_frame
    def patched_render(instance):
        if "app.py" in str(instance.message):
            render_count["spinner1"] += 1
        elif "app_2.py" in str(instance.message):
            render_count["spinner2"] += 1
        original_render(instance)
    spinner_service._render_frame = patched_render
    
    print("\n--- Starting Parallel Spinners ---")
    
    tool1_display = Text("Read ")
    tool1_display.append("(/Users/test/app.py)")
    
    tool2_display = Text("Read ")
    tool2_display.append("(/Users/test/app_2.py)")
    
    spinner_id_1 = spinner_service.start(tool1_display)
    spinner_id_2 = spinner_service.start(tool2_display)
    
    print(f"\n  Started spinner 1: {spinner_id_1}")
    print(f"  Started spinner 2: {spinner_id_2}")
    print(f"  Active spinners: {len(spinner_service._spinners)}")
    print(f"  Animation running: {spinner_service._running}")
    
    print("\n--- Simulating Tool Execution (2 seconds) ---")
    
    # Simulate tool execution with busy wait
    start = time.time()
    while time.time() - start < 2.0:
        time.sleep(0.1)
        
    print(f"\n--- Animation Statistics ---")
    print(f"  Spinner 1 render count: {render_count['spinner1']}")
    print(f"  Spinner 2 render count: {render_count['spinner2']}")
    
    # Stop spinners
    print("\n--- Stopping Spinners ---")
    spinner_service.stop(spinner_id_1, success=True, result_message="Read 34 lines")
    spinner_service.stop(spinner_id_2, success=True, result_message="Read 45 lines")
    
    print(f"\n  Active spinners after stop: {len(spinner_service._spinners)}")
    
    # Check results
    if render_count["spinner1"] > 0 and render_count["spinner2"] > 0:
        print("\n" + "=" * 60)
        print("✓ PASS: Both spinners animated correctly!")
        print("=" * 60)
        return True
    else:
        print("\n" + "=" * 60)
        print("✗ FAIL: Spinners did not animate!")
        print(f"  Expected >0 renders for each spinner")
        print("=" * 60)
        return False


if __name__ == "__main__":
    success = test_spinner_animation()
    sys.exit(0 if success else 1)
