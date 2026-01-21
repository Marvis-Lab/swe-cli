"""Unit tests for TodoHandler, focusing on _find_todo() lookup logic."""

import pytest
from swecli.core.context_engineering.tools.handlers.todo_handler import TodoHandler, TodoItem


class TestTodoHandlerFindTodo:
    """Test suite for TodoHandler._find_todo() method."""

    @pytest.fixture
    def handler(self):
        """Create a TodoHandler with sample todos."""
        handler = TodoHandler()
        # Create some test todos
        handler.create_todo(title="Set up game development environment and project structure")
        handler.create_todo(title="Design core game mechanics (jumping, running, collision detection)")
        handler.create_todo(title="Implement basic level design with platforms and ground")
        handler.create_todo(title="Add enemy characters (Goombas, Koopas) with basic AI")
        return handler

    def test_find_by_exact_todo_id(self, handler):
        """Test finding todo by exact 'todo-X' format ID."""
        actual_id, todo = handler._find_todo("todo-1")
        assert actual_id == "todo-1"
        assert todo is not None
        assert todo.title == "Set up game development environment and project structure"

    def test_find_by_todo_underscore_format(self, handler):
        """Test finding todo by 'todo_X' format (Deep Agent uses this)."""
        # Deep Agent uses underscore instead of dash
        actual_id, todo = handler._find_todo("todo_1")
        assert actual_id == "todo-1"
        assert todo is not None
        assert todo.title == "Set up game development environment and project structure"

        actual_id, todo = handler._find_todo("todo_3")
        assert actual_id == "todo-3"
        assert todo.title == "Implement basic level design with platforms and ground"

    def test_find_by_numeric_zero_based_index(self, handler):
        """Test finding todo by 0-based numeric index (Deep Agent format)."""
        # Deep Agent uses 0-based indexing, should map to todo-1
        actual_id, todo = handler._find_todo("0")
        assert actual_id == "todo-1"
        assert todo is not None
        assert todo.title == "Set up game development environment and project structure"

        # Index 2 should map to todo-3
        actual_id, todo = handler._find_todo("2")
        assert actual_id == "todo-3"
        assert todo.title == "Implement basic level design with platforms and ground"

    def test_find_by_exact_title_case_sensitive(self, handler):
        """Test finding todo by exact title match (case-sensitive)."""
        exact_title = "Design core game mechanics (jumping, running, collision detection)"
        actual_id, todo = handler._find_todo(exact_title)
        assert actual_id == "todo-2"
        assert todo is not None
        assert todo.title == exact_title

    def test_find_by_exact_title_case_insensitive(self, handler):
        """Test finding todo by exact title match (case-insensitive)."""
        # Try with different casing
        actual_id, todo = handler._find_todo("DESIGN CORE GAME MECHANICS (JUMPING, RUNNING, COLLISION DETECTION)")
        assert actual_id == "todo-2"
        assert todo is not None

        # Try with mixed casing
        actual_id, todo = handler._find_todo("design Core GAME mechanics (jumping, running, collision detection)")
        assert actual_id == "todo-2"
        assert todo is not None

    def test_find_by_kebab_case_slug_exact_prefix(self, handler):
        """Test finding todo by kebab-case slug that matches prefix."""
        # "implement-basic-level" should match "Implement basic level design with platforms and ground"
        actual_id, todo = handler._find_todo("implement-basic-level")
        assert actual_id == "todo-3"
        assert todo is not None
        assert todo.title == "Implement basic level design with platforms and ground"

    def test_find_by_kebab_case_slug_partial_words(self, handler):
        """Test finding todo by kebab-case slug with partial words."""
        # "set-up-game" should match "Set up game development environment and project structure"
        actual_id, todo = handler._find_todo("set-up-game")
        assert actual_id == "todo-1"
        assert todo is not None

        # "enemy-characters" should match "Add enemy characters (Goombas, Koopas) with basic AI"
        actual_id, todo = handler._find_todo("enemy-characters")
        assert actual_id == "todo-4"
        assert todo is not None

    def test_find_by_kebab_case_slug_words_in_order(self, handler):
        """Test finding todo by kebab-case slug where words appear in order."""
        # "core-mechanics-jumping" - words appear in order in the title
        actual_id, todo = handler._find_todo("core-mechanics-jumping")
        assert actual_id == "todo-2"
        assert todo is not None

    def test_find_by_partial_string_match(self, handler):
        """Test finding todo by partial string contained in title."""
        # "level design" is contained in "Implement basic level design with platforms and ground"
        actual_id, todo = handler._find_todo("level design")
        assert actual_id == "todo-3"
        assert todo is not None

        # "goombas" is contained in "Add enemy characters (Goombas, Koopas) with basic AI"
        actual_id, todo = handler._find_todo("goombas")
        assert actual_id == "todo-4"
        assert todo is not None

    def test_find_by_partial_case_insensitive(self, handler):
        """Test partial matching is case-insensitive."""
        actual_id, todo = handler._find_todo("LEVEL DESIGN")
        assert actual_id == "todo-3"
        assert todo is not None

        actual_id, todo = handler._find_todo("GoOmBaS")
        assert actual_id == "todo-4"
        assert todo is not None

    def test_find_not_found_returns_none(self, handler):
        """Test that non-existent IDs return None."""
        actual_id, todo = handler._find_todo("nonexistent-todo")
        assert actual_id is None
        assert todo is None

        actual_id, todo = handler._find_todo("todo-999")
        assert actual_id is None
        assert todo is None

        actual_id, todo = handler._find_todo("99")
        assert actual_id is None
        assert todo is None

    def test_find_empty_string_returns_none(self, handler):
        """Test that empty string returns None."""
        actual_id, todo = handler._find_todo("")
        assert actual_id is None
        assert todo is None

    def test_find_with_special_characters(self, handler):
        """Test finding todos with special characters in title."""
        # The title has parentheses
        actual_id, todo = handler._find_todo("Goombas, Koopas")
        assert actual_id == "todo-4"
        assert todo is not None

    def test_find_kebab_case_vs_exact_match_priority(self, handler):
        """Test that exact matches take priority over fuzzy matches."""
        # Create a todo with kebab-case in the actual title
        handler.create_todo(title="test-kebab-case")

        # Should find exact match first
        actual_id, todo = handler._find_todo("test-kebab-case")
        assert todo.title == "test-kebab-case"


class TestTodoHandlerColors:
    """Test suite for todo color markup."""

    @pytest.fixture
    def handler(self):
        """Create a TodoHandler with todos in different states."""
        handler = TodoHandler()
        handler.create_todo(title="Pending task", status="todo")
        handler.create_todo(title="In progress task", status="doing")
        handler.create_todo(title="Completed task", status="done")
        return handler

    def test_format_todo_list_has_colors(self, handler):
        """Test that formatted todo list includes color markup."""
        formatted = handler._format_todo_list_simple()

        # Should have 3 todos
        assert len(formatted) == 3

        # Check that colors are present
        # In progress (doing) should be yellow
        assert any("[yellow]" in line for line in formatted)

        # Pending (todo) should be cyan
        assert any("[cyan]" in line for line in formatted)

        # Completed (done) should be green
        assert any("[green]" in line for line in formatted)

    def test_pending_todo_is_cyan(self, handler):
        """Test that pending todos use cyan color."""
        formatted = handler._format_todo_list_simple()
        pending_line = [line for line in formatted if "Pending task" in line][0]
        assert "[cyan]" in pending_line
        assert "○" in pending_line
        assert "[/cyan]" in pending_line

    def test_in_progress_todo_is_yellow(self, handler):
        """Test that in-progress todos use yellow color."""
        formatted = handler._format_todo_list_simple()
        in_progress_line = [line for line in formatted if "In progress task" in line][0]
        assert "[yellow]" in in_progress_line
        assert "▶" in in_progress_line
        assert "[/yellow]" in in_progress_line

    def test_completed_todo_is_green_with_strikethrough(self, handler):
        """Test that completed todos use green color with strikethrough."""
        formatted = handler._format_todo_list_simple()
        completed_line = [line for line in formatted if "Completed task" in line][0]
        assert "[green]" in completed_line
        assert "✓" in completed_line
        assert "~~" in completed_line  # Strikethrough markup
        assert "[/green]" in completed_line

    def test_write_todos_output_has_colors(self, handler):
        """Test that write_todos output includes color markup."""
        result = handler.write_todos(["New task 1", "New task 2"])
        assert result["success"]

        output = result["output"]
        # Should have cyan color for pending todos
        assert "[cyan]" in output
        assert "○" in output


class TestTodoHandlerUpdateComplete:
    """Test suite for update_todo and complete_todo with fuzzy ID matching."""

    @pytest.fixture
    def handler(self):
        """Create a TodoHandler with sample todos."""
        handler = TodoHandler()
        handler.create_todo(title="Implement basic level design with platforms and ground")
        handler.create_todo(title="Add enemy characters (Goombas, Koopas) with basic AI")
        return handler

    def test_update_todo_with_kebab_case_id(self, handler):
        """Test updating todo using kebab-case slug ID."""
        result = handler.update_todo(id="implement-basic-level", status="doing")
        assert result["success"]
        assert "Implement basic level design" in result["output"]

        # Verify the todo was actually updated
        _, todo = handler._find_todo("implement-basic-level")
        assert todo.status == "doing"

    def test_complete_todo_with_partial_match(self, handler):
        """Test completing todo using partial string match."""
        result = handler.complete_todo(id="enemy characters")
        assert result["success"]
        assert "Add enemy characters" in result["output"]

        # Verify the todo was actually completed
        _, todo = handler._find_todo("enemy characters")
        assert todo.status == "done"

    def test_update_nonexistent_todo_fails(self, handler):
        """Test that updating non-existent todo returns error."""
        result = handler.update_todo(id="nonexistent-task", status="doing")
        assert not result["success"]
        assert "not found" in result["error"]

    def test_complete_nonexistent_todo_fails(self, handler):
        """Test that completing non-existent todo returns error."""
        result = handler.complete_todo(id="nonexistent-task")
        assert not result["success"]
        assert "not found" in result["error"]


class TestTodoCompletionCounter:
    """Test suite for verifying todo completion counter logic."""

    def test_completion_counter_all_done(self):
        """Verify counter shows N/N when all todos are completed."""
        handler = TodoHandler()

        # Create 3 todos
        handler.write_todos(["Task 1", "Task 2", "Task 3"])

        # Mark all as done
        handler.update_todo("todo-1", status="completed")
        handler.update_todo("todo-2", status="completed")
        handler.update_todo("todo-3", status="completed")

        # Verify all have status="done"
        todos = list(handler._todos.values())
        assert len(todos) == 3
        assert all(t.status == "done" for t in todos)

        # Calculate what counter should show
        completed = len([t for t in todos if t.status == "done"])
        total = len(todos)
        assert completed == 3
        assert total == 3

    def test_spinner_callback_guard_no_active_todo(self):
        """Verify spinner callback would be guarded when no active todo exists."""
        handler = TodoHandler()
        handler.write_todos([{"content": "Task 1", "status": "completed"}])

        # All todos are done - spinner callback should be guarded
        todos = list(handler._todos.values())
        has_active = any(t.status == "doing" for t in todos)
        assert not has_active  # Guard would prevent spinner render

    def test_completion_counter_partial_done(self):
        """Verify counter shows correct count when some todos are completed."""
        handler = TodoHandler()

        # Create 4 todos
        handler.write_todos(["Task 1", "Task 2", "Task 3", "Task 4"])

        # Mark 2 as done
        handler.update_todo("todo-1", status="completed")
        handler.update_todo("todo-3", status="completed")

        todos = list(handler._todos.values())
        completed = len([t for t in todos if t.status == "done"])
        total = len(todos)
        assert completed == 2
        assert total == 4

    def test_completion_counter_with_active_todo(self):
        """Verify active todo detection works correctly."""
        handler = TodoHandler()

        # Create 3 todos
        handler.write_todos(["Task 1", "Task 2", "Task 3"])

        # Set one as in_progress
        handler.update_todo("todo-2", status="in_progress")

        todos = list(handler._todos.values())
        has_active = any(t.status == "doing" for t in todos)
        assert has_active  # Should have an active todo
