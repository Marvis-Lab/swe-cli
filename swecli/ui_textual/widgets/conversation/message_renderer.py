from __future__ import annotations

import re
from typing import Any

from rich.text import Text
from textual.widgets import RichLog

from swecli.ui_textual.renderers import render_markdown_text_segment
from swecli.ui_textual.style_tokens import (
    ERROR,
    PRIMARY,
    SUBTLE,
    PANEL_BORDER,
    THINKING,
    THINKING_ICON,
)
from swecli.ui_textual.widgets.conversation.protocols import RichLogInterface


class DefaultMessageRenderer:
    """Handles rendering of user, assistant, and system messages."""

    def __init__(self, log: RichLogInterface, app_callback_interface: Any = None):
        self.log = log
        self.app = app_callback_interface
        self._last_assistant_rendered: str | None = None

    def add_user_message(self, message: str) -> None:
        """Render a user message."""
        # Add blank line before user prompt ONLY if previous line has content.
        # This prevents double spacing when the previous message (assistant, thinking, etc.)
        # already added a trailing blank line.
        #
        # Example flow WITHOUT this check:
        #   add_assistant_message -> adds trailing blank line
        #   add_user_message -> adds leading blank line  <- DOUBLE SPACING
        #
        # With this check, we only add a blank line if the previous line has content.
        if self.log.lines and hasattr(self.log.lines[-1], "plain"):
            last_plain = self.log.lines[-1].plain.strip() if self.log.lines[-1].plain else ""
            if last_plain:
                self.log.write(Text(""))
        self.log.write(Text(f"› {message}", style=f"bold {PRIMARY}"))
        # Only add trailing blank line for non-command messages
        # Commands control their own spacing via print_command_header()
        if not message.strip().startswith("/"):
            self.log.write(Text(""))

    def add_assistant_message(self, message: str) -> None:
        """Render an assistant message, parsing markdown and code blocks."""
        normalized = self._normalize_text(message)
        if normalized and normalized == self._last_assistant_rendered:
            return

        # Add blank line before message if previous line has content (for spacing)
        if self.log.lines and hasattr(self.log.lines[-1], "plain"):
            last_plain = self.log.lines[-1].plain.strip() if self.log.lines[-1].plain else ""
            if last_plain:
                self.log.write(Text(""))

        self._last_assistant_rendered = normalized
        segments = self._split_code_blocks(message)
        text_output = False
        leading_used = False

        for _, segment in enumerate(segments):
            if segment["type"] == "code":
                # Delegate back to log or implement write_code_block here?
                # Ideally, this logic should be self-contained.
                # But _write_code_block is currently in ConversationLog.
                # For now, let's implement the logic here directly or copy it.
                # Since we want to extract, we should move the logic here.
                # But _write_code_block (lines ~530 in ConversationLog) uses Syntax highlighters.
                self._render_code_block(segment)
            else:
                content = segment["content"]
                if not content:
                    continue
                renderables, wrote = render_markdown_text_segment(
                    content,
                    leading=(not text_output and not leading_used),
                )
                for renderable in renderables:
                    self.log.write(renderable)
                if wrote:
                    text_output = True
                    leading_used = True

        self.log.write(Text(""))

    def add_system_message(self, message: str) -> None:
        """Render a system message."""
        self.log.write(Text(message, style=f"{SUBTLE} italic"))

    def add_error(self, message: str) -> None:
        """Render an error message."""
        # Note: stop_spinner is handled by the manager or the main log before calling this?
        # The original code called self.stop_spinner().
        # We might need to handle that in the facade or here.
        # Ideally, rendering just renders. State changes like stopping spinner happen in the caller.
        bullet = Text("⦿ ", style=f"bold {ERROR}")
        bullet.append(message, style=ERROR)
        self.log.write(bullet)
        self.log.write(Text(""))

    def add_command_result(self, lines: list[str], is_error: bool = False) -> None:
        """Render command result lines with tree continuation prefix.

        Used for displaying results from slash commands like /help, /model, etc.
        Uses the same tree prefix (⎿) as tool results for visual consistency.

        Args:
            lines: List of result lines to display
            is_error: If True, use error styling; otherwise use subtle styling
        """
        style = ERROR if is_error else SUBTLE
        for line in lines:
            self.log.write(Text(f"  ⎿  {line}", style=style))
        self.log.write(Text(""))  # Trailing blank line for spacing

    def add_thinking_block(self, content: str) -> None:
        """Render thinking content with dimmed blur effect (60% opacity).

        Displays model reasoning/thinking traces with subtle dark gray styling.
        The dim effect simulates a "blur" appearance by reducing opacity.
        Format: "⟡ First line\n  Subsequent lines indented (2 spaces)"

        Args:
            content: The thinking/reasoning content from the model
        """
        if not content or not content.strip():
            return

        # Add blank line before thinking only if previous line has content
        # (avoids double spacing when add_user_message already added a blank line)
        if self.log.lines and hasattr(self.log.lines[-1], "plain"):
            last_plain = self.log.lines[-1].plain.strip() if self.log.lines[-1].plain else ""
            if last_plain:
                self.log.write(Text(""))

        lines = content.strip().split("\n")
        text = Text()

        # Simulate 60% opacity with dim + darker color for blur effect
        blur_style = f"dim italic {THINKING}"  # THINKING = "#5a5e66"
        icon_style = f"dim {THINKING}"

        # First line with thinking icon (⟡ concave diamond)
        text.append(f"{THINKING_ICON} ", style=icon_style)
        text.append(lines[0], style=blur_style)

        # Subsequent lines indented with 2 spaces to align with text after icon
        for line in lines[1:]:
            text.append(f"\n  {line}", style=blur_style)

        self.log.write(text)
        self.log.write(Text(""))  # Blank line after thinking

    # --- Helpers ---

    def _render_code_block(self, segment: dict[str, str]) -> None:
        """Render a code block segment."""
        from rich.panel import Panel
        from rich.syntax import Syntax

        language = segment.get("language") or "text"
        code = segment.get("content", "")

        # Create syntax object
        syntax = Syntax(
            code,
            language,
            theme="monokai",
            line_numbers=False,
            word_wrap=True,
            padding=1,
        )

        # Wrap in panel
        panel = Panel(
            syntax,
            title=language,
            expand=False,
            border_style=PANEL_BORDER,
            padding=(0, 1),
        )
        self.log.write(panel)

    def _split_code_blocks(self, message: str) -> list[dict[str, str]]:
        pattern = re.compile(r"```(\w+)?\n?(.*?)```", re.DOTALL)
        segments: list[dict[str, str]] = []
        last_end = 0

        for match in pattern.finditer(message):
            start, end = match.span()
            if start > last_end:
                segments.append({"type": "text", "content": message[last_end:start]})

            language = match.group(1) or ""
            code = match.group(2) or ""
            segments.append({"type": "code", "language": language, "content": code})
            last_end = end

        if last_end < len(message):
            segments.append({"type": "text", "content": message[last_end:]})

        if not segments:
            segments.append({"type": "text", "content": message})

        return segments

    @staticmethod
    def _normalize_text(message: str) -> str:
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", message)
        cleaned = cleaned.replace("⏺", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()
