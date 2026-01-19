"""Handler for ask user tool invocations."""

from __future__ import annotations

from typing import Any


class AskUserHandler:
    """Executes user question operations."""

    def __init__(self, ask_user_tool: Any = None):
        """Initialize the handler.

        Args:
            ask_user_tool: AskUserTool instance for asking questions
        """
        self._tool = ask_user_tool

    def ask_questions(self, args: dict[str, Any]) -> dict[str, Any]:
        """Handle user question requests.

        Args:
            args: Dictionary with:
                - questions: List of question dicts with:
                    - question: The question text
                    - header: Short label (max 12 chars)
                    - options: List of {label, description} dicts
                    - multiSelect: Whether to allow multiple selections

        Returns:
            Result dictionary with formatted output
        """
        if not self._tool:
            return {
                "success": False,
                "error": "AskUserTool not available",
                "output": None,
            }

        questions = args.get("questions", [])

        if not questions:
            return {
                "success": False,
                "error": "At least one question is required",
                "output": None,
            }

        # Perform the question asking
        result = self._tool.ask(questions)

        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "output": None,
            }

        if result.get("cancelled"):
            return {
                "success": True,
                "output": "User cancelled the questions",
                "cancelled": True,
                "answers": {},
            }

        # Format the answers for display
        answers = result.get("answers", {})
        output_lines = ["User responses:"]

        for key, value in answers.items():
            if isinstance(value, list):
                value_str = ", ".join(value)
            else:
                value_str = str(value)
            output_lines.append(f"  Question {int(key) + 1}: {value_str}")

        return {
            "success": True,
            "output": "\n".join(output_lines),
            "answers": answers,
            "cancelled": False,
        }
