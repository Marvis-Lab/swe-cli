"""Todo panel widget for displaying persistent todo list."""

from textual.widgets import Static


class TodoPanel(Static):
    """Persistent todo panel showing all todos with status indicators.

    Displays the complete todo list with:
    - Active todos (yellow ▶)
    - Pending todos (gray ○)
    - Completed todos (gray ✓ with strikethrough)

    Toggle visibility with Ctrl+T.
    """

    def __init__(self, todo_handler=None, **kwargs):
        """Initialize the todo panel.

        Args:
            todo_handler: TodoHandler instance for accessing todo state
            **kwargs: Additional widget kwargs
        """
        super().__init__(**kwargs)
        self.todo_handler = todo_handler
        self.border_title = "TODOS"
        self.is_expanded = False  # Track collapsed/expanded state

        # Spinner animation for active tasks
        self._spinner_chars = ["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"]
        self._spinner_index = 0
        self._spinner_timer = None
        self._spinner_active = False

    def on_mount(self) -> None:
        """Called when widget is mounted to the DOM."""
        self.refresh_display()

    def refresh_display(self) -> None:
        """Update the panel with current todos, respecting collapsed/expanded state.

        Shows collapsed summary or full list depending on is_expanded state.
        Auto-shows panel in collapsed state when todos are created.
        """
        if not self.todo_handler:
            self.update("Todo panel not connected")
            return

        todos = list(self.todo_handler._todos.values())

        # Hide when no todos OR all todos are completed
        if not todos or all(t.status == "done" for t in todos):
            self.update("")
            self.border_title = ""
            # Hide completely
            if self.has_class("collapsed"):
                self.remove_class("collapsed")
            if self.has_class("expanded"):
                self.remove_class("expanded")
            self._stop_spinner()
            return

        # Auto-show in collapsed state when todos are created
        if not self.has_class("collapsed") and not self.has_class("expanded"):
            self.add_class("collapsed")
            self.is_expanded = False

        # Render based on current state
        if self.is_expanded:
            self._render_expanded(todos)
        else:
            self._render_collapsed(todos)

    def _render_collapsed(self, todos: list) -> None:
        """Render compact summary with animated spinner for active tasks."""
        total = len(todos)
        active_text = self._get_active_todo_text(todos)

        if active_text:
            # Show spinner + active task text
            spinner = self._spinner_chars[self._spinner_index]
            summary = f"[yellow]{spinner} {active_text}[/yellow] [dim](Press Ctrl+T to expand/hide)[/dim]"

            # Start spinner if not already running
            if not self._spinner_active:
                self._start_spinner()
        else:
            # No active task - show completion progress
            completed = len([t for t in todos if t.status == "done"])
            summary = f"{completed}/{total} completed [dim](Press Ctrl+T to expand/hide)[/dim]"

            # Stop spinner
            self._stop_spinner()

        self.update(summary)
        self.border_title = ""  # No border title in collapsed mode

    def _render_expanded(self, todos: list) -> None:
        """Render full todo list with status indicators."""
        # Update border title with count
        self.border_title = f"TODOS ({len(todos)} total)"

        # Sort todos by status: doing -> todo -> done
        status_order = {"doing": 0, "todo": 1, "done": 2}
        sorted_todos = sorted(
            todos,
            key=lambda t: (status_order.get(t.status, 3), t.id)
        )

        # Build display content
        lines = []

        for todo in sorted_todos:
            if todo.status == "done":
                # Completed: gray with strikethrough
                lines.append(f"[dim]✓ [strike]{todo.title}[/strike][/dim]")
            elif todo.status == "doing":
                # In-progress: yellow
                lines.append(f"[yellow]▶ {todo.title}[/yellow]")
            else:
                # Pending: gray
                lines.append(f"[dim]○ {todo.title}[/dim]")

        # Join all lines and update display
        self.update("\n".join(lines))

    def _get_active_todo_text(self, todos: list) -> str | None:
        """Get the activeForm or title of the currently active todo.

        Args:
            todos: List of TodoItem objects

        Returns:
            The active_form (or title as fallback) of the first todo with status "doing",
            or None if no active todo
        """
        for todo in todos:
            if todo.status == "doing":
                # Prefer active_form (present continuous) for spinner display
                return todo.active_form if todo.active_form else todo.title
        return None

    def _start_spinner(self) -> None:
        """Start the spinner animation timer."""
        if self._spinner_timer is not None:
            return  # Already running

        self._spinner_active = True
        self._spinner_index = 0
        self._spinner_timer = self.set_timer(0.15, self._animate_spinner)

    def _stop_spinner(self) -> None:
        """Stop the spinner animation timer."""
        self._spinner_active = False
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _animate_spinner(self) -> None:
        """Advance spinner animation to next frame."""
        if not self._spinner_active:
            return

        # Advance to next frame
        self._spinner_index = (self._spinner_index + 1) % len(self._spinner_chars)

        # Re-render collapsed view with new spinner frame
        if self.todo_handler:
            todos = list(self.todo_handler._todos.values())
            if todos and self.has_class("collapsed"):
                self._render_collapsed(todos)

        # Schedule next frame
        self._spinner_timer = self.set_timer(0.15, self._animate_spinner)

    def toggle_expansion(self) -> None:
        """Toggle between collapsed and expanded states."""
        if self.is_expanded:
            # Collapse
            self.is_expanded = False
            self.remove_class("expanded")
            self.add_class("collapsed")
        else:
            # Expand
            self.is_expanded = True
            self.remove_class("collapsed")
            self.add_class("expanded")

            # Stop spinner when expanding
            self._stop_spinner()

        self.refresh_display()

    def on_unmount(self) -> None:
        """Clean up timer when widget unmounts."""
        self._stop_spinner()
