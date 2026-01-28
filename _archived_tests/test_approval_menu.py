"""Test the new interactive approval menu."""

import sys
from rich.console import Console

from swecli.core.approval import ApprovalManager
from swecli.models.operation import Operation, OperationType

def test_approval_menu():
    """Test the approval menu with different operations."""
    console = Console()
    approval_manager = ApprovalManager(console)

    console.print("\n[bold cyan]═══════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]  SWE-CLI Approval Menu Test[/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════════════[/bold cyan]\n")

    # Test 1: File write operation
    console.print("[bold]Test 1: File Write Operation[/bold]")
    console.print("[dim]Use arrow keys to navigate, Enter to select, or press 1/2/3[/dim]\n")

    operation = Operation(
        type=OperationType.FILE_WRITE,
        target="test_file.py",
        parameters={"content": "def hello():\n    print('Hello, World!')\n"},
    )

    preview = """def hello():
    print('Hello, World!')
"""

    try:
        # Note: This will be interactive - you need to actually select an option
        console.print("[yellow]Please interact with the menu below:[/yellow]")
        result = approval_manager.request_approval(operation, preview)

        console.print("\n[green]✓ Result:[/green]")
        console.print(f"  Approved: {result.approved}")
        console.print(f"  Choice: {result.choice.value}")
        console.print(f"  Apply to all: {result.apply_to_all}")
        console.print(f"  Cancelled: {result.cancelled}\n")

    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]\n")
        import traceback
        traceback.print_exc()
        return False

    # Test 2: Bash command
    console.print("\n[bold]Test 2: Bash Command Operation[/bold]\n")

    operation2 = Operation(
        type=OperationType.BASH_EXECUTE,
        target="ls -la",
    )

    preview2 = "ls -la"

    try:
        result2 = approval_manager.request_approval(operation2, preview2)

        console.print("\n[green]✓ Result:[/green]")
        console.print(f"  Approved: {result2.approved}")
        console.print(f"  Choice: {result2.choice.value}")
        console.print(f"  Apply to all: {result2.apply_to_all}\n")

    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]\n")
        import traceback
        traceback.print_exc()
        return False

    console.print("[bold green]✅ All approval menu tests completed![/bold green]\n")
    return True

if __name__ == "__main__":
    console = Console()
    console.print("\n[bold yellow]Note:[/bold yellow] This test requires interactive input.")
    console.print("You'll see an interactive menu. Try these:")
    console.print("  • Arrow keys (↑/↓) to navigate")
    console.print("  • Enter to select")
    console.print("  • Press 1, 2, or 3 directly")
    console.print("  • Shift+Tab for 'Approve All'")
    console.print("  • Esc for 'No'\n")

    try:
        success = test_approval_menu()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Test interrupted by user[/yellow]")
        sys.exit(1)
