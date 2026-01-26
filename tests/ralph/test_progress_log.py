"""Tests for Ralph progress log."""

import pytest
from datetime import datetime
from pathlib import Path

from swecli.ralph.models.progress import RalphProgressLog, ProgressEntry


class TestProgressEntry:
    """Tests for ProgressEntry model."""

    def test_create_success_entry(self):
        """Test creating a successful progress entry."""
        entry = ProgressEntry(
            story_id="US-001",
            summary="Implemented feature X",
            files_changed=["src/main.py", "tests/test_main.py"],
            learnings=["Pattern A works well", "Avoid pattern B"],
            success=True,
        )

        assert entry.story_id == "US-001"
        assert entry.success is True
        assert len(entry.files_changed) == 2
        assert len(entry.learnings) == 2
        assert entry.error is None

    def test_create_failure_entry(self):
        """Test creating a failed progress entry."""
        entry = ProgressEntry(
            story_id="US-002",
            summary="Failed to implement",
            files_changed=[],
            learnings=[],
            success=False,
            error="Tests failed",
        )

        assert entry.success is False
        assert entry.error == "Tests failed"


class TestRalphProgressLog:
    """Tests for RalphProgressLog."""

    @pytest.fixture
    def progress_path(self, tmp_path):
        """Create a temporary progress file path."""
        return tmp_path / "progress.txt"

    def test_initialize(self, progress_path):
        """Test initializing a new progress log."""
        log = RalphProgressLog(progress_path)
        log.initialize()

        assert progress_path.exists()
        content = progress_path.read_text()
        assert "# Ralph Progress Log" in content
        assert "## Codebase Patterns" in content

    def test_append_entry(self, progress_path):
        """Test appending a progress entry."""
        log = RalphProgressLog(progress_path)
        log.initialize()

        entry = ProgressEntry(
            story_id="US-001",
            summary="Implemented feature",
            files_changed=["file1.py"],
            learnings=["Learning 1"],
            success=True,
        )

        log.append_entry(entry)

        content = progress_path.read_text()
        assert "US-001" in content
        assert "Implemented feature" in content
        assert "file1.py" in content
        assert "Learning 1" in content

    def test_append_multiple_entries(self, progress_path):
        """Test appending multiple entries preserves all."""
        log = RalphProgressLog(progress_path)
        log.initialize()

        for i in range(3):
            entry = ProgressEntry(
                story_id=f"US-00{i+1}",
                summary=f"Story {i+1}",
                files_changed=[],
                learnings=[],
                success=True,
            )
            log.append_entry(entry)

        content = progress_path.read_text()
        assert "US-001" in content
        assert "US-002" in content
        assert "US-003" in content

    def test_add_pattern(self, progress_path):
        """Test adding codebase patterns."""
        log = RalphProgressLog(progress_path)
        log.initialize()

        log.add_pattern("Use pattern X for Y")
        log.add_pattern("Always check Z")

        patterns = log.get_codebase_patterns()
        assert len(patterns) == 2
        assert "Use pattern X for Y" in patterns

    def test_add_duplicate_pattern_ignored(self, progress_path):
        """Test that duplicate patterns are not added."""
        log = RalphProgressLog(progress_path)
        log.initialize()

        log.add_pattern("Pattern A")
        log.add_pattern("Pattern A")  # Duplicate

        patterns = log.get_codebase_patterns()
        assert len(patterns) == 1

    def test_get_context_for_agent(self, progress_path):
        """Test getting context for agent injection."""
        log = RalphProgressLog(progress_path)
        log.initialize()

        log.add_pattern("Pattern 1")
        log.add_pattern("Pattern 2")

        context = log.get_context_for_agent()
        assert "Codebase Patterns" in context
        assert "Pattern 1" in context
        assert "Pattern 2" in context

    def test_get_iteration_count(self, progress_path):
        """Test counting iterations."""
        log = RalphProgressLog(progress_path)
        log.initialize()

        assert log.get_iteration_count() == 0

        # Add entries
        for i in range(3):
            entry = ProgressEntry(
                story_id=f"US-00{i+1}",
                summary=f"Story {i+1}",
                files_changed=[],
                learnings=[],
                success=True,
            )
            log.append_entry(entry)

        assert log.get_iteration_count() == 3

    def test_parse_existing_log(self, progress_path):
        """Test parsing an existing progress log."""
        # Create a log with patterns
        progress_path.write_text("""# Ralph Progress Log
Started: 2024-01-01 10:00:00

## Codebase Patterns
- Pattern A
- Pattern B

---

## [2024-01-01 10:00:00] - US-001
- Implemented feature

---
""")

        log = RalphProgressLog(progress_path)
        patterns = log.get_codebase_patterns()

        assert len(patterns) == 2
        assert "Pattern A" in patterns
        assert "Pattern B" in patterns
