#!/usr/bin/env python3
"""Test the new Braille dots spinner."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from swecli.ui.animations import Spinner
from rich.console import Console

console = Console()

print("Testing Braille Dots Spinner")
print("=" * 50)

# Show the frames
from swecli.ui.animations import Spinner as S
print(f"\nSpinner frames: {' '.join(S.FRAMES)}")
print(f"Total frames: {len(S.FRAMES)}")
print("Pattern: ⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏")

# Test the spinner animation
print("\n" + "=" * 50)
print("Running spinner for 3 seconds...")
print("=" * 50 + "\n")

spinner = Spinner(console)
spinner.start("Thinking with new Braille dots...")

time.sleep(3)

spinner.stop()

print("\n" + "=" * 50)
print("✅ Spinner test complete!")
print("=" * 50)
