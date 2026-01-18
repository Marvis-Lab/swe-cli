import pytest
from swecli.core.agents.components.plan_parser import parse_plan, ParsedPlan

def test_parse_plan_valid():
    text = """
---BEGIN PLAN---
## Goal
Refactor the codebase

## Implementation Steps
1. Delete unused files
2. Fix linting errors
---END PLAN---
"""
    plan = parse_plan(text)
    assert plan is not None
    assert plan.is_valid()
    assert plan.goal == "Refactor the codebase"
    assert len(plan.steps) == 2
    assert plan.steps[0] == "Delete unused files"
    assert plan.steps[1] == "Fix linting errors"

def test_parse_plan_invalid():
    text = "Some random text"
    plan = parse_plan(text)
    assert plan is None

def test_parse_plan_partial():
    # Only checks if it parses what's available
    text = """
---BEGIN PLAN---
## Goal
Do something

## Implementation Steps
1. Step 1
---END PLAN---
"""
    plan = parse_plan(text)
    assert plan is not None
    assert plan.goal == "Do something"
    assert plan.steps == ["Step 1"]
