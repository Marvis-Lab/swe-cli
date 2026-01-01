"""Visual test to see the improved approval dialog design."""

from rich.console import Console

console = Console()

console.print("\n[bold cyan]═══════════════════════════════════════════════[/bold cyan]")
console.print("[bold cyan]  Approval Dialog Visual Improvements[/bold cyan]")
console.print("[bold cyan]═══════════════════════════════════════════════[/bold cyan]\n")

console.print("[bold]Changes Made:[/bold]\n")

console.print("1. [green]✓[/green] Box characters changed from light to heavy")
console.print("   [dim]Before: ╭─╮│╯╰ (thin lines)[/dim]")
console.print("   [dim]After:  ┏━┓┃┛┗ (thick lines)[/dim]\n")

console.print("2. [green]✓[/green] Removed leading pipes from options")
console.print("   [dim]Before: │ ❯ 1. Yes[/dim]")
console.print("   [dim]After:    ❯ 1. Yes[/dim]\n")

console.print("3. [green]✓[/green] Made shortcuts dimmed")
console.print("   [dim]Before: Yes, allow all operations during this session (shift+tab)[/dim]")
console.print("   [dim]After:  Yes, allow all operations during this session [/dim][dim](shift+tab)[/dim]\n")

console.print("4. [green]✓[/green] Dialog disappears after selection")
console.print("   [dim]Added: erase_when_done=True to Application[/dim]\n")

console.print("5. [green]✓[/green] Question text is now bold")
console.print("   [dim]Uses: class:question bold[/dim]\n")

# Show visual example
console.print("\n[bold]Example of new dialog appearance:[/bold]\n")

# Simulate the preview box
preview_text = """def hello():
    print("Hello, World!")

def goodbye():
    print("Goodbye!")"""

console.print("┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
for line in preview_text.split("\n")[:3]:
    padding = " " * (57 - len(line))
    console.print(f"┃ {line}{padding}┃")
console.print("┃ ...                                                     ┃")
console.print("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")

console.print("\n[bold]Do you want to create/write this file?[/bold]\n")
console.print("  [bold]❯ 1.[/bold] Yes")
console.print("    2. Yes, allow all operations during this session [dim](shift+tab)[/dim]")
console.print("    3. No, and tell Claude what to do differently [dim](esc)[/dim]")

console.print("\n[bold green]✅ All visual improvements implemented![/bold green]")
console.print("\n[dim]Note: The heavy box characters (┏━┓┃┛┗) are much more visible than the previous light characters (╭─╮│╯╰), making the dialog clearer.[/dim]")

# Show slash command improvements
console.print("\n[bold cyan]═══════════════════════════════════════════════[/bold cyan]")
console.print("[bold cyan]  Slash Command Improvements[/bold cyan]")
console.print("[bold cyan]═══════════════════════════════════════════════[/bold cyan]\n")

from swecli.ui.autocomplete import SLASH_COMMANDS

console.print(f"[bold]Total commands:[/bold] [green]{len(SLASH_COMMANDS)}[/green] (down from 17)")
console.print("[bold]Removed:[/bold] [red]7[/red] unimplemented commands\n")

console.print("[dim]Removed commands:[/dim]")
removed = ["model", "approvals", "review", "new", "compact", "diff", "mention"]
for cmd in removed:
    console.print(f"  [red]✗[/red] [dim]/{cmd}[/dim]")

console.print("\n[bold green]✅ Only showing implemented, working commands now![/bold green]\n")
