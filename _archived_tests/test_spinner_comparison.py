#!/usr/bin/env python3
"""Compare different spinner speeds."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from swecli.ui.animations import Spinner
from rich.console import Console

console = Console()

print("=" * 60)
print("Spinner Speed Comparison")
print("=" * 60)
print()

# Current speed
print("✓ New Braille Dots Spinner")
print("  Frames: ⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏")
print(f"  Speed: {Spinner.INTERVAL}s ({int(Spinner.INTERVAL * 1000)}ms) per frame")
print(f"  Full cycle: {Spinner.INTERVAL * len(Spinner.FRAMES):.2f}s")
print(f"  Cycles per second: {1 / (Spinner.INTERVAL * len(Spinner.FRAMES)):.1f}")
print()

# Show animation for 3 seconds
print("Animation demo (3 seconds):")
print("-" * 60)

spinner = Spinner(console)
spinner.start("Processing your request...")

time.sleep(3)

spinner.stop()

print()
print("-" * 60)
print("✓ Speed is good!")
print()
print("If you want it even faster, I can reduce to 0.04s (40ms)")
print("If you want it slower, I can increase to 0.06s (60ms)")
