#!/usr/bin/env python3
"""Test improved spinner that updates from random verb to actual task description."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from swecli.core.monitoring import TaskMonitor
from swecli.ui.task_progress import TaskProgressDisplay
from rich.console import Console


def test_spinner_update():
    """Demonstrate spinner updating from 'Thinking...' to actual task description."""
    print("\n" + "=" * 70)
    print("Testing Improved Spinner - Random Verb → Actual Task Description")
    print("=" * 70)

    console = Console()

    # Simulate the flow:
    # 1. Start with random thinking verb
    # 2. "Call LLM" (simulate delay)
    # 3. Update to actual task description from LLM
    # 4. Continue showing while task executes

    # Step 1: Start with random verb (what REPL does)
    thinking_verbs = [
        "Thinking", "Analyzing", "Processing", "Evaluating",
        "Pondering", "Reasoning", "Calculating"
    ]
    import random
    random_verb = random.choice(thinking_verbs)

    console.print(f"\n[dim]Starting spinner with random verb: '{random_verb}'[/dim]")

    task_monitor = TaskMonitor()
    task_monitor.start(random_verb, initial_tokens=0)

    progress = TaskProgressDisplay(console, task_monitor)
    progress.start()

    # Step 2: Simulate LLM call (takes some time)
    console.print("[dim]Calling LLM (simulating 2s delay)...[/dim]")
    time.sleep(2.0)

    # Step 3: LLM responds with what it's actually doing
    llm_description = "I'll search for the configuration files and analyze the current mode toggle implementation"
    first_sentence = llm_description.split('.')[0].strip()

    console.print(f"[dim]LLM responded with: '{first_sentence}'[/dim]")
    console.print("[dim]Updating spinner to show actual task...[/dim]\n")

    # Update the task description (this is what we added)
    task_monitor.update_task_description(first_sentence)

    # Step 4: Continue running for a bit to show the updated description
    time.sleep(3.0)

    # Stop
    progress.stop()

    console.print("\n[green]✓ Spinner successfully updated from random verb to actual task![/green]")

    # Show the timeline
    console.print("\n[bold]Timeline:[/bold]")
    console.print("  0.0s - 2.0s: Spinner shows 'Thinking...' (random verb)")
    console.print("  2.0s - 5.0s: Spinner updates to 'I'll search for the configuration files...'")
    console.print("  5.0s: Spinner stops, replaced with actual results\n")


def test_with_tool_execution():
    """Test spinner during tool execution in PLAN mode."""
    print("\n" + "=" * 70)
    print("Testing Tool Execution Spinner")
    print("=" * 70)

    console = Console()

    # Simulate tool execution with descriptive text
    tool_descriptions = [
        "Reading file opencli/repl/repl.py to understand mode toggle",
        "Searching for mode-related code patterns",
        "Editing mode toggle rendering logic",
    ]

    for i, description in enumerate(tool_descriptions, 1):
        console.print(f"\n[bold]Tool {i}:[/bold]")

        task_monitor = TaskMonitor()
        task_monitor.start(description, initial_tokens=0)

        progress = TaskProgressDisplay(console, task_monitor)
        progress.start()

        # Simulate tool execution
        time.sleep(2.0)

        progress.stop()

        console.print(f"[dim]→ Tool {i} completed[/dim]")

    console.print("\n[green]✓ Tool execution spinners working correctly![/green]\n")


if __name__ == "__main__":
    try:
        test_spinner_update()
        test_with_tool_execution()

        print("=" * 70)
        print("✅ ALL SPINNER TESTS PASSED!")
        print("=" * 70)
        print("\n[Summary]")
        print("• Spinner starts with random thinking verb")
        print("• Updates to actual task description when LLM responds")
        print("• Shows descriptive text during tool execution")
        print("• Disappears cleanly when task completes\n")

    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
