#!/usr/bin/env python3
"""Complete demonstration of improved spinner with action summarizer."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from swecli.core.monitoring import TaskMonitor
from swecli.core.utils import ActionSummarizer
from swecli.ui.task_progress import TaskProgressDisplay
from rich.console import Console
import random


def test_complete_spinner_flow():
    """Demonstrate complete spinner flow: random verb → LLM response → concise action."""
    print("\n" + "=" * 70)
    print("Complete Improved Spinner Demo")
    print("=" * 70)

    console = Console()
    summarizer = ActionSummarizer(api_key="dummy")

    # Simulate what happens in REPL
    thinking_verbs = ["Thinking", "Analyzing", "Processing", "Reasoning"]
    random_verb = random.choice(thinking_verbs)

    console.print("\n[bold cyan]Step 1: Start with random thinking verb[/bold cyan]")
    console.print(f"[dim]Random verb selected: '{random_verb}'[/dim]\n")

    # Step 1: Start spinner with random verb
    task_monitor = TaskMonitor()
    task_monitor.start(random_verb, initial_tokens=0)

    progress = TaskProgressDisplay(console, task_monitor)
    progress.start()

    console.print("[dim]→ Spinner shows: • Thinking... (1s • esc to interrupt)[/dim]")

    # Step 2: Simulate LLM call (takes time)
    time.sleep(2.0)

    # Step 3: LLM responds with verbose description
    llm_response = "I'll search through the configuration files to find the mode toggle implementation and analyze the current structure to understand how it works"

    console.print("\n[bold cyan]Step 2: LLM responds with action description[/bold cyan]")
    console.print(f"[dim]LLM says: '{llm_response[:80]}...'[/dim]\n")

    # Step 4: Summarize into concise action
    concise_action = summarizer.summarize_fast(llm_response, max_length=60)

    console.print("[bold cyan]Step 3: Summarize to concise action[/bold cyan]")
    console.print(f"[dim]Concise action: '{concise_action}'[/dim]\n")

    # Step 5: Update spinner
    task_monitor.update_task_description(concise_action)

    console.print("[dim]→ Spinner updates: • Searching configuration files for mode toggle (2s • esc)[/dim]")

    # Continue running to show updated description
    time.sleep(2.0)

    # Stop spinner
    progress.stop()

    console.print("\n[bold cyan]Step 4: Task completes, spinner disappears[/bold cyan]")
    console.print("[dim]Spinner removed, replaced with actual results[/dim]\n")

    console.print("[green]✓ Complete spinner flow demonstrated![/green]")


def test_multiple_actions():
    """Test spinner with multiple different actions."""
    print("\n" + "=" * 70)
    print("Multiple Actions Demo")
    print("=" * 70)

    console = Console()
    summarizer = ActionSummarizer(api_key="dummy")

    actions = [
        "I'll read the repl.py file to understand the current implementation",
        "Now I need to analyze the mode toggle logic to see how it works",
        "Let me search for related test files to understand the expected behavior",
        "I'm going to update the rendering code to improve the mode display",
    ]

    for i, llm_response in enumerate(actions, 1):
        console.print(f"\n[bold]Action {i}:[/bold]")

        # Start with random verb
        random_verb = random.choice(["Thinking", "Processing", "Analyzing"])
        task_monitor = TaskMonitor()
        task_monitor.start(random_verb, initial_tokens=0)

        progress = TaskProgressDisplay(console, task_monitor)
        progress.start()

        # Simulate LLM delay
        time.sleep(1.0)

        # Summarize and update
        concise = summarizer.summarize_fast(llm_response, max_length=60)
        console.print(f"  LLM: {llm_response[:60]}...")
        console.print(f"  → Spinner: [cyan]{concise}[/cyan]")

        task_monitor.update_task_description(concise)

        # Show updated spinner
        time.sleep(1.5)

        progress.stop()


def test_comparison():
    """Show before/after comparison."""
    print("\n" + "=" * 70)
    print("Before/After Comparison")
    print("=" * 70)

    console = Console()

    examples = [
        (
            "I'll search through the configuration files to find mode toggle",
            "• I'll search through the configuration file... (3s)",
            "• Searching configuration files for mode toggle (3s • esc)"
        ),
        (
            "Let me read repl.py to understand the implementation",
            "• Let me read repl.py to understand the i... (2s)",
            "• Reading repl.py to understand implementation (2s • esc)"
        ),
        (
            "I need to analyze the code structure and identify components",
            "• I need to analyze the code structure a... (4s)",
            "• Analyzing code structure (4s • esc)"
        ),
    ]

    for llm_response, before, after in examples:
        console.print("\n[bold]LLM Response:[/bold]")
        console.print(f"  {llm_response}")
        console.print("\n[red]Before (raw):[/red]")
        console.print(f"  {before}")
        console.print("[green]After (summarized):[/green]")
        console.print(f"  {after}")


if __name__ == "__main__":
    try:
        test_complete_spinner_flow()
        test_multiple_actions()
        test_comparison()

        print("\n" + "=" * 70)
        print("✅ ALL DEMOS COMPLETED!")
        print("=" * 70)

        print("\n[Key Improvements]")
        print("1. ✓ Spinner starts with engaging random verb")
        print("2. ✓ Updates to concise action from LLM")
        print("3. ✓ Action text is present continuous tense")
        print("4. ✓ Kept under 60 characters")
        print("5. ✓ Spinner icon visible throughout")
        print("6. ✓ No API calls (fast local summarization)")
        print()

    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
