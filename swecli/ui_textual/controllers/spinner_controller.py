"""Spinner controller for the Textual chat app."""

from __future__ import annotations

import random
import time
from typing import Optional, TYPE_CHECKING

from rich.text import Text
from textual.timer import Timer

if TYPE_CHECKING:  # pragma: no cover
    from swecli.ui_textual.chat_app import SWECLIChatApp
    from swecli.ui_textual.components import TipsManager
    from swecli.core.context_engineering.tools.todo_handler import TodoHandler


class SpinnerController:
    """Manages the in-conversation spinner animation."""

    def __init__(
        self,
        app: "SWECLIChatApp",
        tips_manager: "TipsManager",
        todo_handler: Optional["TodoHandler"] = None,
    ) -> None:
        self.app = app
        self.tips_manager = tips_manager
        self.todo_handler = todo_handler
        self._frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._timer: Timer | None = None
        self._frame_index = 0
        self._message = "Thinking…"
        self._started_at = 0.0
        self._active = False
        self._current_tip = ""

    @property
    def active(self) -> bool:
        return self._active

    def start(self, message: Optional[str] = None) -> None:
        if self._timer is not None:
            return

        conversation = getattr(self.app, "conversation", None)
        if conversation is None:
            return

        if message is not None:
            self._message = message
        else:
            # Try to get activeForm from current in_progress todo
            active_todo_msg = None
            if self.todo_handler:
                active_todo_msg = self.todo_handler.get_active_todo_message()
            if active_todo_msg:
                self._message = active_todo_msg
            else:
                self._message = self._default_message()

        self._frame_index = 0
        self._started_at = time.monotonic()
        self._active = True
        self._current_tip = self.tips_manager.get_next_tip() if self.tips_manager else ""
        self._render(initial=True)
        self._timer = self.app.set_interval(0.12, self._advance_frame)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

        conversation = getattr(self.app, "conversation", None)
        if self._active and conversation is not None:
            conversation.stop_spinner()

        self._active = False
        self._started_at = 0.0
        self._current_tip = ""

    def resume(self) -> None:
        if not self._active:
            self.start(self._default_message())
        else:
            # Restart timer to refresh animation if already marked active
            if self._timer is not None:
                self._timer.stop()
            self._timer = self.app.set_interval(0.12, self._advance_frame)

    def _advance_frame(self) -> None:
        if not self._active:
            return

        self._frame_index = (self._frame_index + 1) % len(self._frames)
        self._render(initial=False)

    def _render(self, *, initial: bool) -> None:
        conversation = getattr(self.app, "conversation", None)
        if conversation is None:
            return

        text = self._format_spinner_text()
        if initial:
            conversation.start_spinner(text)
        else:
            conversation.update_spinner(text)

    def _format_spinner_text(self) -> Text:
        frame = self._frames[self._frame_index]
        elapsed = 0
        if self._started_at:
            elapsed = int(time.monotonic() - self._started_at)
        suffix = f" ({elapsed}s)" if elapsed else " (0s)"

        renderable = Text()
        renderable.append(frame, style="bright_cyan")
        renderable.append(f" {self._message}{suffix}", style="bright_cyan")

        if self._current_tip:
            renderable.append("\n")
            grey = "#a0a4ad"
            renderable.append("  ⎿  Tip: ", style=grey)
            renderable.append(self._current_tip, style=grey)

        return renderable

    @staticmethod
    def _default_message() -> str:
        try:
            from swecli.repl.query_processor import QueryProcessor

            verb = random.choice(QueryProcessor.THINKING_VERBS)
        except Exception:
            verb = "Thinking"
        return f"{verb}…"
