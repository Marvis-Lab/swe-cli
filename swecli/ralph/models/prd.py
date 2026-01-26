"""Pydantic models for Ralph PRD (Product Requirements Document)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class UserStory(BaseModel):
    """A single user story in the PRD."""

    id: str = Field(..., description="Unique story identifier (e.g., US-001)")
    title: str = Field(..., description="Short descriptive title")
    description: str = Field(..., description="Full user story description")
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        alias="acceptanceCriteria",
        description="List of acceptance criteria that must be met",
    )
    priority: int = Field(default=1, description="Priority order (1 = highest)")
    passes: bool = Field(default=False, description="Whether story has passed quality gates")
    notes: str = Field(default="", description="Implementation notes or comments")

    model_config = {"populate_by_name": True}


class RalphPRD(BaseModel):
    """Ralph Product Requirements Document.

    This model represents the prd.json file that tracks the project's
    user stories and their completion status.
    """

    project: str = Field(..., description="Project name")
    branch_name: str = Field(
        ..., alias="branchName", description="Git branch for this PRD (e.g., ralph/feature-name)"
    )
    description: str = Field(..., description="High-level project description")
    user_stories: list[UserStory] = Field(
        default_factory=list, alias="userStories", description="List of user stories to implement"
    )

    model_config = {"populate_by_name": True}

    @classmethod
    def load(cls, path: Path) -> RalphPRD:
        """Load PRD from a JSON file.

        Args:
            path: Path to prd.json file

        Returns:
            Loaded RalphPRD instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If JSON is invalid
        """
        if not path.exists():
            raise FileNotFoundError(f"PRD file not found: {path}")

        try:
            with open(path, "r") as f:
                data = json.load(f)
            return cls.model_validate(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in PRD file: {e}") from e

    def save(self, path: Path) -> None:
        """Save PRD to a JSON file.

        Args:
            path: Path to save prd.json
        """
        with open(path, "w") as f:
            json.dump(self.model_dump(by_alias=True), f, indent=2)

    def get_next_story(self) -> Optional[UserStory]:
        """Get the next story to work on.

        Returns the highest priority story that hasn't passed yet.

        Returns:
            Next UserStory to implement, or None if all complete
        """
        incomplete = [s for s in self.user_stories if not s.passes]
        if not incomplete:
            return None

        # Sort by priority (lower = higher priority)
        incomplete.sort(key=lambda s: s.priority)
        return incomplete[0]

    def is_complete(self) -> bool:
        """Check if all user stories have passed.

        Returns:
            True if all stories pass, False otherwise
        """
        return all(s.passes for s in self.user_stories)

    def mark_story_complete(self, story_id: str) -> bool:
        """Mark a story as complete (passes=True).

        Args:
            story_id: ID of the story to mark complete

        Returns:
            True if story was found and marked, False otherwise
        """
        for story in self.user_stories:
            if story.id == story_id:
                story.passes = True
                return True
        return False

    def get_story_by_id(self, story_id: str) -> Optional[UserStory]:
        """Get a story by its ID.

        Args:
            story_id: Story ID to find

        Returns:
            UserStory if found, None otherwise
        """
        for story in self.user_stories:
            if story.id == story_id:
                return story
        return None

    def get_progress_summary(self) -> str:
        """Get a summary of PRD progress.

        Returns:
            Human-readable progress summary
        """
        total = len(self.user_stories)
        completed = sum(1 for s in self.user_stories if s.passes)
        remaining = total - completed

        lines = [
            f"Project: {self.project}",
            f"Branch: {self.branch_name}",
            f"Progress: {completed}/{total} stories complete",
            "",
        ]

        if remaining > 0:
            lines.append("Remaining stories:")
            for story in sorted(
                [s for s in self.user_stories if not s.passes], key=lambda s: s.priority
            ):
                lines.append(f"  [{story.id}] {story.title} (priority: {story.priority})")
        else:
            lines.append("All stories complete!")

        return "\n".join(lines)
