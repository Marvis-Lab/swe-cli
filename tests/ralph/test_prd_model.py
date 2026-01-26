"""Tests for Ralph PRD model."""

import json
import pytest
from pathlib import Path

from swecli.ralph.models.prd import RalphPRD, UserStory


class TestUserStory:
    """Tests for UserStory model."""

    def test_create_basic_story(self):
        """Test creating a basic user story."""
        story = UserStory(
            id="US-001",
            title="Test Story",
            description="Test description",
            acceptance_criteria=["Criterion 1", "Criterion 2"],
            priority=1,
        )

        assert story.id == "US-001"
        assert story.title == "Test Story"
        assert story.passes is False
        assert len(story.acceptance_criteria) == 2

    def test_story_alias_serialization(self):
        """Test that acceptanceCriteria alias works."""
        data = {
            "id": "US-001",
            "title": "Test",
            "description": "Test",
            "acceptanceCriteria": ["A", "B"],
            "priority": 1,
            "passes": False,
            "notes": "",
        }

        story = UserStory.model_validate(data)
        assert story.acceptance_criteria == ["A", "B"]

        # Serialize should use alias
        dumped = story.model_dump(by_alias=True)
        assert "acceptanceCriteria" in dumped


class TestRalphPRD:
    """Tests for RalphPRD model."""

    @pytest.fixture
    def sample_prd_data(self):
        """Sample PRD data."""
        return {
            "project": "TestProject",
            "branchName": "ralph/test-feature",
            "description": "Test feature description",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "First Story",
                    "description": "First story description",
                    "acceptanceCriteria": ["A", "B"],
                    "priority": 1,
                    "passes": False,
                    "notes": "",
                },
                {
                    "id": "US-002",
                    "title": "Second Story",
                    "description": "Second story description",
                    "acceptanceCriteria": ["C"],
                    "priority": 2,
                    "passes": True,
                    "notes": "",
                },
                {
                    "id": "US-003",
                    "title": "Third Story",
                    "description": "Third story description",
                    "acceptanceCriteria": ["D"],
                    "priority": 3,
                    "passes": False,
                    "notes": "",
                },
            ],
        }

    def test_create_prd(self, sample_prd_data):
        """Test creating a PRD from data."""
        prd = RalphPRD.model_validate(sample_prd_data)

        assert prd.project == "TestProject"
        assert prd.branch_name == "ralph/test-feature"
        assert len(prd.user_stories) == 3

    def test_get_next_story(self, sample_prd_data):
        """Test getting the next incomplete story."""
        prd = RalphPRD.model_validate(sample_prd_data)

        next_story = prd.get_next_story()
        assert next_story is not None
        assert next_story.id == "US-001"  # Highest priority incomplete

    def test_get_next_story_all_complete(self, sample_prd_data):
        """Test that get_next_story returns None when all complete."""
        sample_prd_data["userStories"][0]["passes"] = True
        sample_prd_data["userStories"][2]["passes"] = True
        prd = RalphPRD.model_validate(sample_prd_data)

        next_story = prd.get_next_story()
        assert next_story is None

    def test_is_complete(self, sample_prd_data):
        """Test is_complete check."""
        prd = RalphPRD.model_validate(sample_prd_data)
        assert prd.is_complete() is False

        # Mark all complete
        for story in prd.user_stories:
            story.passes = True

        assert prd.is_complete() is True

    def test_mark_story_complete(self, sample_prd_data):
        """Test marking a story complete."""
        prd = RalphPRD.model_validate(sample_prd_data)

        assert prd.user_stories[0].passes is False
        result = prd.mark_story_complete("US-001")

        assert result is True
        assert prd.user_stories[0].passes is True

    def test_mark_story_complete_not_found(self, sample_prd_data):
        """Test marking non-existent story."""
        prd = RalphPRD.model_validate(sample_prd_data)

        result = prd.mark_story_complete("US-999")
        assert result is False

    def test_get_story_by_id(self, sample_prd_data):
        """Test getting story by ID."""
        prd = RalphPRD.model_validate(sample_prd_data)

        story = prd.get_story_by_id("US-002")
        assert story is not None
        assert story.title == "Second Story"

        missing = prd.get_story_by_id("US-999")
        assert missing is None

    def test_save_and_load(self, sample_prd_data, tmp_path):
        """Test saving and loading PRD."""
        prd = RalphPRD.model_validate(sample_prd_data)
        prd_path = tmp_path / "prd.json"

        # Save
        prd.save(prd_path)
        assert prd_path.exists()

        # Verify JSON structure
        with open(prd_path) as f:
            saved_data = json.load(f)
        assert "userStories" in saved_data  # Uses alias

        # Load
        loaded = RalphPRD.load(prd_path)
        assert loaded.project == prd.project
        assert len(loaded.user_stories) == len(prd.user_stories)

    def test_load_missing_file(self, tmp_path):
        """Test loading non-existent file raises error."""
        with pytest.raises(FileNotFoundError):
            RalphPRD.load(tmp_path / "missing.json")

    def test_get_progress_summary(self, sample_prd_data):
        """Test progress summary generation."""
        prd = RalphPRD.model_validate(sample_prd_data)

        summary = prd.get_progress_summary()
        assert "TestProject" in summary
        assert "1/3" in summary  # 1 complete, 3 total
        assert "US-001" in summary  # Remaining story
