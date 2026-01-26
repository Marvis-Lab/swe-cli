"""RalphAgent - Wraps SwecliAgent with Ralph-specific behavior."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from swecli.core.agents.swecli_agent import SwecliAgent
from swecli.ralph.models.prd import RalphPRD, UserStory
from swecli.ralph.models.progress import RalphProgressLog


RALPH_SYSTEM_PROMPT = """# Ralph Agent Instructions

You are an autonomous coding agent working on a software project.

## Your Task

You are implementing a specific user story. Work autonomously to complete it.

## Current Story

{story_context}

## Codebase Context

{codebase_context}

## Instructions

1. Implement the user story according to the acceptance criteria
2. Keep changes focused and minimal
3. Follow existing code patterns in the codebase
4. Run quality checks before finishing (typecheck, lint, test)
5. Document any learnings or patterns discovered

## Quality Requirements

- ALL code must pass typecheck, lint, and tests
- Do NOT commit broken code
- Keep changes focused and minimal
- Follow existing code patterns

## Output Format

When you complete your work, provide a summary in this format:

SUMMARY: [Brief description of what was implemented]
FILES_CHANGED: [Comma-separated list of files modified]
LEARNINGS: [Any patterns or gotchas discovered, separated by | ]
STATUS: [success or failed]

If you encounter blocking issues, set STATUS: failed and explain the issue.
"""


@dataclass
class RalphAgentResult:
    """Result from a Ralph agent iteration."""

    success: bool
    summary: str
    files_changed: list[str]
    learnings: list[str]
    error: Optional[str] = None
    raw_output: str = ""


class RalphAgent:
    """Agent for executing a single Ralph iteration.

    Wraps SwecliAgent with Ralph-specific system prompt and behavior.
    Each iteration gets a FRESH agent instance with no prior context.
    """

    def __init__(
        self,
        swecli_agent: SwecliAgent,
        prd: RalphPRD,
        progress_log: RalphProgressLog,
        working_dir: Path,
    ):
        """Initialize Ralph agent.

        Args:
            swecli_agent: Base SwecliAgent to wrap
            prd: Current PRD being worked on
            progress_log: Progress log for context injection
            working_dir: Project working directory
        """
        self.agent = swecli_agent
        self.prd = prd
        self.progress_log = progress_log
        self.working_dir = working_dir

    def _build_story_context(self, story: UserStory) -> str:
        """Build context string for a user story.

        Args:
            story: The user story to describe

        Returns:
            Formatted story context
        """
        criteria = "\n".join(f"  - {c}" for c in story.acceptance_criteria)

        return f"""
Story ID: {story.id}
Title: {story.title}
Priority: {story.priority}

Description:
{story.description}

Acceptance Criteria:
{criteria}

Notes: {story.notes or 'None'}
"""

    def _build_system_prompt(self, story: UserStory) -> str:
        """Build the Ralph system prompt for a story.

        Args:
            story: The story being implemented

        Returns:
            Complete system prompt
        """
        story_context = self._build_story_context(story)
        codebase_context = self.progress_log.get_context_for_agent()

        return RALPH_SYSTEM_PROMPT.format(
            story_context=story_context, codebase_context=codebase_context or "(No prior context)"
        )

    def _parse_output(self, output: str) -> RalphAgentResult:
        """Parse the agent's output into structured result.

        Args:
            output: Raw agent output

        Returns:
            Parsed RalphAgentResult
        """
        result = RalphAgentResult(
            success=False, summary="", files_changed=[], learnings=[], raw_output=output
        )

        lines = output.split("\n")
        current_section = None
        section_lines: list[str] = []

        for line in lines:
            stripped = line.strip()

            # Check for section headers (with or without colon)
            if stripped.upper().startswith("SUMMARY"):
                if current_section == "summary" and section_lines:
                    result.summary = " ".join(section_lines)
                current_section = "summary"
                section_lines = []
                # Handle inline content after SUMMARY: or SUMMARY
                rest = stripped[7:].lstrip(":").strip()
                if rest:
                    section_lines.append(rest)
            elif stripped.upper().startswith("FILES_CHANGED") or stripped.upper().startswith("FILES CHANGED"):
                if current_section == "summary" and section_lines:
                    result.summary = " ".join(section_lines)
                current_section = "files"
                section_lines = []
            elif stripped.upper().startswith("LEARNINGS"):
                if current_section == "files" and section_lines:
                    result.files_changed = [f.strip().lstrip("- ") for f in section_lines if f.strip()]
                current_section = "learnings"
                section_lines = []
            elif stripped.upper().startswith("STATUS"):
                if current_section == "learnings" and section_lines:
                    result.learnings = [ln.strip().lstrip("- ") for ln in section_lines if ln.strip()]
                current_section = "status"
                rest = stripped[6:].lstrip(":").strip().lower()
                result.success = rest == "success"
            elif stripped.upper().startswith("ERROR"):
                result.error = stripped[5:].lstrip(":").strip()
            elif stripped and current_section:
                # Collect lines for current section
                section_lines.append(stripped)

        # Finalize any remaining section
        if current_section == "summary" and section_lines:
            result.summary = " ".join(section_lines)
        elif current_section == "files" and section_lines:
            result.files_changed = [f.strip().lstrip("- ") for f in section_lines if f.strip()]
        elif current_section == "learnings" and section_lines:
            result.learnings = [ln.strip().lstrip("- ") for ln in section_lines if ln.strip()]

        # If no structured output was found, treat as success with full output as summary
        if not result.summary and output.strip():
            result.summary = output[:500] if len(output) > 500 else output
            # If agent produced output without explicit STATUS, assume success
            result.success = True

        return result

    def execute_story(
        self,
        story: UserStory,
        deps: Any,
        max_iterations: int = 30,
        task_monitor: Optional[Any] = None,
        ui_callback: Optional[Any] = None,
    ) -> RalphAgentResult:
        """Execute a single user story.

        CRITICAL: This uses a FRESH message history each time.
        This is Ralph's core pattern - no context carryover between iterations.

        Args:
            story: The user story to implement
            deps: Agent dependencies (mode_manager, approval_manager, etc.)
            max_iterations: Max agent loop iterations
            task_monitor: Optional task monitor for interrupts
            ui_callback: Optional UI callback for progress

        Returns:
            RalphAgentResult with implementation results
        """
        # Build the full context including codebase patterns
        codebase_context = self.progress_log.get_context_for_agent()
        story_context = self._build_story_context(story)

        # Create a message with story context and codebase patterns
        user_message = f"""Please implement this user story:

{story_context}

{codebase_context}

Work autonomously to implement this story. When done, provide your output in the specified format with SUMMARY, FILES_CHANGED, LEARNINGS, and STATUS fields."""

        # CRITICAL: Fresh message history (None) - no prior context
        # This is Ralph's core pattern for avoiding context overflow
        import logging

        logger = logging.getLogger(__name__)

        try:
            result = self.agent.run_sync(
                message=user_message,
                deps=deps,
                message_history=None,  # FRESH context each iteration
                max_iterations=max_iterations,
                task_monitor=task_monitor,
                ui_callback=ui_callback,
            )

            logger.info(f"Agent result success: {result.get('success')}")
            logger.info(f"Agent result content (first 500 chars): {str(result.get('content', ''))[:500]}")

            if not result.get("success", False):
                error_content = result.get("content", "Unknown error")
                logger.warning(f"Agent failed with: {error_content}")
                return RalphAgentResult(
                    success=False,
                    summary="Agent execution failed",
                    files_changed=[],
                    learnings=[],
                    error=error_content,
                    raw_output=str(result),
                )

            content = result.get("content", "")
            parsed = self._parse_output(content)
            logger.info(f"Parsed result - success: {parsed.success}, summary: {parsed.summary[:100] if parsed.summary else 'None'}")
            return parsed

        except Exception as e:
            return RalphAgentResult(
                success=False,
                summary="Agent execution raised exception",
                files_changed=[],
                learnings=[],
                error=str(e),
                raw_output="",
            )
