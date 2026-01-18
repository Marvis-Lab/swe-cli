"""Parser for structured implementation plans."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedPlan:
    """A parsed implementation plan with structured sections."""

    goal: str = ""
    steps: list[str] = field(default_factory=list)
    raw_text: str = ""

    def is_valid(self) -> bool:
        """Check if the plan has required fields."""
        return bool(self.goal and self.steps)

    def get_todo_items(self) -> list[dict]:
        """Convert plan steps to todo items format.

        Returns:
            List of todo items with content, status, and activeForm
        """
        todos = []
        for step in self.steps:
            # Generate activeForm from step (convert to present continuous)
            active_form = self._generate_active_form(step)
            todos.append({
                "content": step,
                "status": "pending",
                "activeForm": active_form,
            })
        return todos

    @staticmethod
    def _generate_active_form(step: str) -> str:
        """Generate present continuous form from step description.

        Args:
            step: The step description (e.g., "Create validation schema")

        Returns:
            Present continuous form (e.g., "Creating validation schema")
        """
        # Simple heuristic: find first verb and convert to -ing form
        words = step.split()
        if not words:
            return step

        first_word = words[0]

        # Common verb conversions
        verb_map = {
            "add": "Adding",
            "create": "Creating",
            "update": "Updating",
            "modify": "Modifying",
            "implement": "Implementing",
            "fix": "Fixing",
            "remove": "Removing",
            "delete": "Deleting",
            "write": "Writing",
            "read": "Reading",
            "test": "Testing",
            "run": "Running",
            "build": "Building",
            "install": "Installing",
            "configure": "Configuring",
            "setup": "Setting up",
            "refactor": "Refactoring",
            "move": "Moving",
            "rename": "Renaming",
            "import": "Importing",
            "export": "Exporting",
            "integrate": "Integrating",
            "verify": "Verifying",
            "check": "Checking",
        }

        lower_first = first_word.lower()
        if lower_first in verb_map:
            return f"{verb_map[lower_first]} {' '.join(words[1:])}"

        # Generic -ing conversion
        if first_word.endswith("e"):
            ing_form = first_word[:-1] + "ing"
        elif first_word.endswith("ie"):
            ing_form = first_word[:-2] + "ying"
        else:
            ing_form = first_word + "ing"

        return f"{ing_form.capitalize()} {' '.join(words[1:])}"


def parse_plan(text: str) -> Optional[ParsedPlan]:
    """Parse structured plan from ---BEGIN PLAN--- to ---END PLAN---.

    Args:
        text: Full text containing the plan

    Returns:
        ParsedPlan object if found, None otherwise
    """
    # Find plan block
    match = re.search(r"---BEGIN PLAN---(.*?)---END PLAN---", text, re.DOTALL)
    if not match:
        return None

    plan_content = match.group(1).strip()
    plan = ParsedPlan(raw_text=plan_content)

    # Parse Goal section
    goal_match = re.search(r"##\s*Goal\s*\n(.*?)(?=\n##|\Z)", plan_content, re.DOTALL)
    if goal_match:
        plan.goal = goal_match.group(1).strip()

    # Parse Implementation Steps section
    steps_match = re.search(
        r"##\s*Implementation Steps\s*\n(.*?)(?=\n##|\Z)", plan_content, re.DOTALL
    )
    if steps_match:
        plan.steps = _parse_numbered_list(steps_match.group(1))

    return plan


def _parse_numbered_list(text: str) -> list[str]:
    """Parse a numbered list (1. item) into list of strings."""
    items = []
    for line in text.strip().split("\n"):
        line = line.strip()
        # Match "1. ", "2. ", etc.
        match = re.match(r"^\d+\.\s+(.+)$", line)
        if match:
            items.append(match.group(1).strip())
    return items


def extract_plan_from_response(response: str) -> Optional[ParsedPlan]:
    """Extract plan from assistant response, handling partial plans.

    Args:
        response: Full assistant response text

    Returns:
        ParsedPlan if found, None otherwise
    """
    # First try exact format
    plan = parse_plan(response)
    if plan and plan.is_valid():
        return plan

    # If no valid plan found, return None
    return None
