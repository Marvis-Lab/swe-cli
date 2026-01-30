"""Handler for the ask-user subagent."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class AskUserSubAgentHandler:
    """Handles execution of the ask-user subagent."""

    def execute(
        self,
        task: str,
        ui_callback: Any,
    ) -> dict[str, Any]:
        """Execute the ask-user built-in subagent.

        This is a special subagent that shows a UI panel for user input
        instead of running an LLM. It parses questions from the task JSON
        and displays them in an interactive panel.

        Args:
            task: JSON string containing questions (from spawn_subagent prompt)
            ui_callback: UI callback with access to app

        Returns:
            Result dict with user's answers
        """
        # Parse questions from task (JSON string)
        try:
            questions_data = json.loads(task)
            questions = self.parse_questions(questions_data.get("questions", []))
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": "Invalid questions format - expected JSON",
                "content": "",
            }

        if not questions:
            return {
                "success": False,
                "error": "No questions provided",
                "content": "",
            }

        # Get app reference from ui_callback
        app = getattr(ui_callback, "chat_app", None) or getattr(ui_callback, "_app", None)
        if app is None:
            # Try to get app from nested callback parent
            parent = getattr(ui_callback, "_parent_callback", None)
            if parent:
                app = getattr(parent, "chat_app", None) or getattr(parent, "_app", None)

        if app is None:
            return {
                "success": False,
                "error": "UI app not available for ask-user",
                "content": "",
            }

        # Show panel and wait for user response using call_from_thread pattern
        # (similar to approval_manager.py)
        if not hasattr(app, "call_from_thread") or not getattr(app, "is_running", False):
            return {
                "success": False,
                "error": "UI app not available or not running for ask-user",
                "content": "",
            }

        done_event = threading.Event()
        result_holder: dict[str, Any] = {"answers": None, "error": None}

        def invoke_panel() -> None:
            async def run_panel() -> None:
                try:
                    result_holder["answers"] = await app._ask_user_controller.start(
                        questions
                    )
                except Exception as exc:
                    result_holder["error"] = exc
                finally:
                    done_event.set()

            app.run_worker(
                run_panel(),
                name="ask-user-panel",
                exclusive=True,
                exit_on_error=False,
            )

        try:
            app.call_from_thread(invoke_panel)

            # Wait for user response with timeout
            if not done_event.wait(timeout=600):  # 10 min timeout
                return {
                    "success": False,
                    "error": "Ask user timed out",
                    "content": "",
                }

            if result_holder["error"]:
                raise result_holder["error"]

            answers = result_holder["answers"]
        except Exception as e:
            logger.exception("Ask user failed")
            return {
                "success": False,
                "error": f"Ask user failed: {e}",
                "content": "",
            }

        if answers is None:
            return {
                "success": True,
                "content": "User cancelled/skipped the question(s).",
                "answers": {},
                "cancelled": True,
            }

        # Format answers for agent consumption (compact single line for clean UI display)
        # Get headers from original questions for better formatting
        answer_parts = []
        for idx, ans in answers.items():
            if isinstance(ans, list):
                ans_text = ", ".join(str(a) for a in ans)
            else:
                ans_text = str(ans)
            # Try to get header from question, fall back to Q#
            q_idx = int(idx) if idx.isdigit() else 0
            header = f"Q{q_idx + 1}"
            if q_idx < len(questions):
                q = questions[q_idx]
                if hasattr(q, "header") and q.header:
                    header = q.header
            answer_parts.append(f"[{header}]={ans_text}")

        total = len(questions)
        answered = len(answers)
        answer_summary = ", ".join(answer_parts) if answer_parts else "No answers"

        return {
            "success": True,
            "content": f"Received {answered}/{total} answers: {answer_summary}",
            "answers": answers,
            "cancelled": False,
        }

    def parse_questions(self, questions_data: list) -> list:
        """Parse question dicts into Question objects.

        Args:
            questions_data: List of question dictionaries from JSON

        Returns:
            List of Question objects
        """
        from swecli.core.context_engineering.tools.implementations.ask_user_tool import (
            Question,
            QuestionOption,
        )

        questions = []
        for q in questions_data:
            if not isinstance(q, dict):
                continue

            options = []
            for opt in q.get("options", []):
                if isinstance(opt, dict):
                    options.append(
                        QuestionOption(
                            label=opt.get("label", ""),
                            description=opt.get("description", ""),
                        )
                    )
                else:
                    options.append(QuestionOption(label=str(opt)))

            if options:
                questions.append(
                    Question(
                        question=q.get("question", ""),
                        header=q.get("header", "")[:12],
                        options=options,
                        multi_select=q.get("multiSelect", False),
                    )
                )
        return questions
