"""Panel messages for agent creation wizard using Rich components."""

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from swecli.ui_textual.style_tokens import BLUE_BG_ACTIVE, BLUE_LIGHT, GREY


def create_location_panel(selected_index: int, working_dir: str = "") -> RenderableType:
    """Create location selection panel using Rich components.

    Args:
        selected_index: Currently selected option (0=Project, 1=Personal)
        working_dir: Working directory path for display in project option

    Returns:
        Rich Panel renderable
    """
    # Build project path label - show actual path if available
    if working_dir:
        project_label = f"Project ({working_dir}/.swecli/agents/)"
    else:
        project_label = "Project (.swecli/agents/)"

    items = [
        {
            "option": "1",
            "label": project_label,
            "summary": "Local to this repository",
        },
        {"option": "2", "label": "Personal (~/.swecli/agents/)", "summary": "Available everywhere"},
    ]

    table = Table.grid(expand=False, padding=(0, 1))
    table.add_column(width=2, justify="center")  # Pointer
    table.add_column(width=7, justify="center")  # Option number
    table.add_column(ratio=1)  # Label
    table.add_column(ratio=1)  # Summary

    for row_index, item in enumerate(items):
        is_active = row_index == selected_index
        pointer = "❯" if is_active else " "
        row_style = f"on {BLUE_BG_ACTIVE}" if is_active else ""
        pointer_style = "bold bright_cyan" if is_active else "dim"
        label_style = "bold white" if is_active else "white"
        summary_style = "dim white" if is_active else "dim"
        option_style = "bold bright_cyan" if is_active else "dim"
        table.add_row(
            Text(pointer, style=pointer_style),
            Text(item["option"], style=option_style),
            Text(item["label"], style=label_style),
            Text(item["summary"], style=summary_style),
            style=row_style,
        )

    instructions = Text(
        "Use ↑/↓ or 1-2 to select, Enter to confirm, Esc to cancel.",
        style=f"italic {GREY}",
    )
    header = Text("Choose where to create the agent.", style=BLUE_LIGHT)

    return Panel(
        Group(header, table, instructions),
        title="[bold]Create New Agent[/bold]",
        title_align="left",
        border_style="bright_cyan",
        padding=(1, 2),
    )


def create_method_panel(selected_index: int) -> RenderableType:
    """Create creation method selection panel using Rich components.

    Args:
        selected_index: Currently selected option (0=Generate, 1=Manual, 2=Back)

    Returns:
        Rich Panel renderable
    """
    items = [
        {
            "option": "1",
            "label": "Generate with Claude",
            "summary": "AI creates the agent definition",
        },
        {
            "option": "2",
            "label": "Manual configuration",
            "summary": "Write the system prompt yourself",
        },
        {"option": "B", "label": "← Back", "summary": "Return to previous step"},
    ]

    table = Table.grid(expand=False, padding=(0, 1))
    table.add_column(width=2, justify="center")  # Pointer
    table.add_column(width=7, justify="center")  # Option number
    table.add_column(ratio=1)  # Label
    table.add_column(ratio=1)  # Summary

    for row_index, item in enumerate(items):
        is_active = row_index == selected_index
        pointer = "❯" if is_active else " "
        row_style = f"on {BLUE_BG_ACTIVE}" if is_active else ""
        pointer_style = "bold bright_cyan" if is_active else "dim"
        label_style = "bold white" if is_active else "white"
        summary_style = "dim white" if is_active else "dim"
        option_style = "bold bright_cyan" if is_active else "dim"
        table.add_row(
            Text(pointer, style=pointer_style),
            Text(item["option"], style=option_style),
            Text(item["label"], style=label_style),
            Text(item["summary"], style=summary_style),
            style=row_style,
        )

    instructions = Text(
        "Use ↑/↓ or 1-2 to select, Enter to confirm, B to go back, Esc to cancel.",
        style=f"italic {GREY}",
    )
    header = Text("How should the agent be created?", style=BLUE_LIGHT)

    return Panel(
        Group(header, table, instructions),
        title="[bold]Creation Method[/bold]",
        title_align="left",
        border_style="bright_blue",
        padding=(1, 2),
    )


def create_identifier_input_panel(current_value: str = "", error: str = "") -> RenderableType:
    """Create agent identifier input panel using Rich components.

    Args:
        current_value: Current text in input field
        error: Error message to display (if any)

    Returns:
        Rich Panel renderable
    """
    header = Text("Enter a unique identifier for your agent:", style=BLUE_LIGHT)
    hint = Text("e.g., test-runner, code-reviewer, tech-lead", style="dim")

    elements = [header, hint]

    if error:
        elements.append(Text(f"⚠ {error}", style="bold yellow"))

    # Input field visualization
    display_value = current_value if current_value else ""
    input_width = 50
    if len(display_value) > input_width:
        display_value = display_value[-(input_width - 3) :] + "..."

    input_text = Text()
    input_text.append("[", style="dim")
    input_text.append(display_value, style="bold bright_green")
    input_text.append(" " * max(0, input_width - len(display_value)), style="")
    input_text.append("]", style="dim")
    elements.append(input_text)

    instructions = Text(
        "Type in the input box below. Press Enter to confirm, Esc to cancel.",
        style=f"italic {GREY}",
    )
    elements.append(instructions)

    return Panel(
        Group(*elements),
        title="[bold]Agent Identifier[/bold]",
        title_align="left",
        border_style="bright_cyan",
        padding=(1, 2),
    )


def create_prompt_input_panel(current_value: str = "") -> RenderableType:
    """Create system prompt input panel using Rich components.

    Args:
        current_value: Current text in input field

    Returns:
        Rich Panel renderable
    """
    header = Text("Enter the system prompt for your agent:", style=BLUE_LIGHT)
    hint = Text("Be comprehensive for best results", style="dim")

    elements = [header, hint]

    # Show preview of input (first few lines)
    input_width = 50
    if current_value:
        preview_lines = current_value.split("\n")[:3]
        for pline in preview_lines:
            if len(pline) > input_width:
                pline = pline[: input_width - 3] + "..."
            input_text = Text()
            input_text.append("[", style="dim")
            input_text.append(pline, style="bold bright_green")
            input_text.append(" " * max(0, input_width - len(pline)), style="")
            input_text.append("]", style="dim")
            elements.append(input_text)
        if len(current_value.split("\n")) > 3:
            more_count = len(current_value.split("\n")) - 3
            elements.append(Text(f"... (+{more_count} more lines)", style="dim"))
    else:
        input_text = Text()
        input_text.append("[", style="dim")
        input_text.append(" " * input_width, style="")
        input_text.append("]", style="dim")
        elements.append(input_text)

    instructions = Text(
        "Type in the input box below. Press Enter to confirm, Esc to cancel.",
        style=f"italic {GREY}",
    )
    elements.append(instructions)

    return Panel(
        Group(*elements),
        title="[bold]System Prompt[/bold]",
        title_align="left",
        border_style="bright_cyan",
        padding=(1, 2),
    )


def create_description_input_panel(current_value: str = "") -> RenderableType:
    """Create description input panel for AI generation using Rich components.

    Args:
        current_value: Current text in input field

    Returns:
        Rich Panel renderable
    """
    header = Text(
        "Describe what this agent should do and when it should be used:", style=BLUE_LIGHT
    )
    hint = Text("Be comprehensive for best results", style="dim")

    elements = [header, hint]

    # Input field visualization
    input_width = 50
    if current_value:
        preview_lines = current_value.split("\n")[:3]
        for pline in preview_lines:
            if len(pline) > input_width:
                pline = pline[: input_width - 3] + "..."
            input_text = Text()
            input_text.append("[", style="dim")
            input_text.append(pline, style="bold bright_green")
            input_text.append(" " * max(0, input_width - len(pline)), style="")
            input_text.append("]", style="dim")
            elements.append(input_text)
    else:
        input_text = Text()
        input_text.append("[", style="dim")
        input_text.append(" " * input_width, style="")
        input_text.append("]", style="dim")
        elements.append(input_text)

    instructions = Text(
        "Type in the input box below. Press Enter to confirm, Esc to cancel.",
        style=f"italic {GREY}",
    )
    elements.append(instructions)

    return Panel(
        Group(*elements),
        title="[bold]Describe Your Agent[/bold]",
        title_align="left",
        border_style="bright_cyan",
        padding=(1, 2),
    )


def create_generating_panel(description: str = "") -> RenderableType:
    """Create panel showing generation in progress using Rich components.

    Args:
        description: The description being used for generation

    Returns:
        Rich Panel renderable
    """
    header = Text("Claude is creating your agent...", style="bold yellow")

    elements = [header]

    if description:
        elements.append(Text("Based on:", style="dim"))
        # Show first 80 chars of description
        preview = description[:80] + "..." if len(description) > 80 else description
        elements.append(Text(f"  {preview}", style="dim"))

    return Panel(
        Group(*elements),
        title="[bold]Generating Agent[/bold]",
        title_align="left",
        border_style="bright_yellow",
        padding=(1, 2),
    )


def create_success_panel(agent_name: str, agent_path: str) -> RenderableType:
    """Create success panel after agent creation using Rich components.

    Args:
        agent_name: Name of the created agent
        agent_path: Path to the agent file

    Returns:
        Rich Panel renderable
    """
    header = Text(f"✓ Created agent: {agent_name}", style="bold bright_green")

    # Show path (potentially truncated)
    display_path = agent_path
    max_path_len = 55
    if len(display_path) > max_path_len:
        display_path = "..." + display_path[-(max_path_len - 3) :]

    location_label = Text("Location:", style="dim")
    location_path = Text(f"  {display_path}", style="white")
    instructions = Text("Use /agents list to see all agents", style=f"italic {GREY}")

    return Panel(
        Group(header, location_label, location_path, instructions),
        title="[bold]Agent Created[/bold]",
        title_align="left",
        border_style="bright_green",
        padding=(1, 2),
    )
