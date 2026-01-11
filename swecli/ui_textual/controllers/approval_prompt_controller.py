"""Controller for inline approval prompts within the Textual chat app."""

from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from rich.console import Group
from rich.panel import Panel
from rich.text import Text


class ApprovalPromptController:
    """Encapsulates the inline approval prompt state machine."""

    def __init__(self, app: "SWECLIChatApp") -> None:
        if TYPE_CHECKING:  # pragma: no cover
            pass

        self.app = app
        self._active = False
        self._future: asyncio.Future[tuple[bool, str, str]] | None = None
        self._options: list[dict[str, Any]] = []
        self._selected_index = 0
        self._command: str = ""
        self._working_dir: str = "."
        self._header_rendered = False  # Track if tool header was rendered

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active

    async def start(self, command: str, working_dir: str) -> tuple[bool, str, str]:
        """Display the approval prompt and wait for a choice."""

        if self._future is not None:
            raise RuntimeError("Approval prompt already active")

        self._command = command or ""
        self._working_dir = working_dir or "."
        base_prefix = ""
        if self._command.strip():
            base_prefix = self._command.strip().split()[0]
        auto_desc = (
            f"Automatically approve commands starting with '{base_prefix}' in {self._working_dir}."
            if base_prefix
            else f"Automatically approve future commands in {self._working_dir}."
        )
        self._options = [
            {"choice": "1", "label": "Yes", "description": "Run this command now.", "approved": True},
            {
                "choice": "2",
                "label": "Yes, and don't ask again",
                "description": auto_desc,
                "approved": True,
            },
            {
                "choice": "3",
                "label": "No",
                "description": "Cancel and adjust your request.",
                "approved": False,
            },
        ]
        self._selected_index = 0
        self._active = True

        loop = asyncio.get_running_loop()
        self._future = loop.create_future()

        self.app.input_field.load_text("")

        controller = getattr(self.app, "_autocomplete_controller", None)
        if controller is not None:
            controller.reset()

        conversation = self.app.conversation
        # V2: Pause the tool widget spinner during approval (if using widget-based log)
        current_widget = getattr(conversation, "_current_tool_widget", None)
        if current_widget is not None and hasattr(current_widget, "_timer"):
            timer = current_widget._timer
            if timer is not None:
                timer.stop()
                current_widget._timer = None
        # V1 fallback: pause old-style spinner (attributes are on _tool_renderer)
        else:
            tool_renderer = getattr(conversation, "_tool_renderer", None)
            if tool_renderer is not None and getattr(tool_renderer, "_tool_call_start", None) is not None:
                timer = getattr(tool_renderer, "_tool_spinner_timer", None)
                if timer is not None:
                    timer.stop()
                    tool_renderer._tool_spinner_timer = None
                tool_renderer._spinner_active = False
                tool_renderer._replace_tool_call_line("⏺")

        self._render()
        self.app.input_field.focus()

        try:
            result = await self._future
        finally:
            self._cleanup()

        return result

    def render(self) -> None:
        """Re-render the prompt if it is active."""
        self._render()

    def move(self, delta: int) -> None:
        if not self._active or not self._options:
            return
        self._selected_index = (self._selected_index + delta) % len(self._options)
        self._render()

    def confirm(self) -> None:
        if not self._active or not self._future or self._future.done():
            return

        option = self._options[self._selected_index]
        edited_command = self.app.input_field.text.strip() or self._command
        result = (option.get("approved", True), option["choice"], edited_command)

        conversation = self.app.conversation

        conversation.clear_approval_prompt()

        # V2: Check for widget-based tool call
        current_widget = getattr(conversation, "_current_tool_widget", None)
        # V1: Check for line-based tool call (attributes are on _tool_renderer)
        tool_renderer = getattr(conversation, "_tool_renderer", None)
        call_display = getattr(tool_renderer, "_tool_display", None) if tool_renderer else None
        call_start = getattr(tool_renderer, "_tool_call_start", None) if tool_renderer else None

        if option.get("approved", True):
            # Approved: start spinner (will be stopped by on_tool_result)
            if current_widget is not None:
                conversation.start_tool_execution()
            elif call_display is not None:
                conversation.start_tool_execution()
        else:
            # Denied: show error state
            # V2: The spinner was stopped in start(), on_tool_result will handle the rest
            # V1 fallback: handle old-style tool calls
            if call_start is not None and tool_renderer is not None:
                # DON'T truncate - preserve subagent history
                # Just update the tool line in-place with red bullet and show interrupt message
                timer = getattr(tool_renderer, "_tool_spinner_timer", None)
                if timer is not None:
                    timer.stop()
                    tool_renderer._tool_spinner_timer = None
                tool_renderer._spinner_active = False

                # Update the tool line in-place with red bullet (preserves subagent history)
                tool_renderer._replace_tool_call_line("⏺", success=False)

                # Add interrupt message after current content
                from swecli.ui_textual.utils.interrupt_utils import create_interrupt_text, APPROVAL_INTERRUPT_MESSAGE
                result_line = create_interrupt_text(APPROVAL_INTERRUPT_MESSAGE)
                conversation.write(result_line, scroll_end=True, animate=False)
                conversation.write(Text(""))
            # Note: We don't show "Command cancelled." for the else case
            # because on_tool_result handles this for V2, and the approval modal shows cancellation.
            if call_display is not None and tool_renderer is not None:
                tool_renderer._tool_display = None
            if call_start is not None and tool_renderer is not None:
                tool_renderer._tool_call_start = None

        self._future.set_result(result)

    def cancel(self) -> None:
        if not self._active or not self._options:
            return
        self._selected_index = len(self._options) - 1
        self._render()
        self.confirm()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        conversation = self.app.conversation
        conversation.clear_approval_prompt()
        self._future = None
        self._active = False
        self._options = []
        self._selected_index = 0
        self._header_rendered = False  # Reset for next approval
        controller = getattr(self.app, "_autocomplete_controller", None)
        if controller is not None:
            controller.reset()
        self.app.input_field.focus()
        self.app.input_field.load_text("")

    def _render(self) -> None:
        if not self._active:
            return

        conversation = self.app.conversation

        # Build tool header (only on first render - it persists after approval)
        tool_header = None
        if not self._header_rendered:
            from swecli.ui_textual.utils.tool_display import format_tool_call
            header_text = format_tool_call("run_command", {"command": self._command or ""})
            tool_header = Text()
            tool_header.append("⏺ ", style="green")
            tool_header.append(header_text)
            self._header_rendered = True

        cmd_display = self._command or "(empty command)"

        header = Text.assemble(
            ("Command", "dim"),
            (" · ", "dim"),
            (cmd_display, "bold bright_cyan"),
        )
        location = Text.assemble(
            ("Directory", "dim"),
            (" · ", "dim"),
            (self._working_dir, "dim"),
        )
        hint = Text("↑/↓ choose · Enter confirm · Esc cancel", style="dim")

        option_lines: list[Text] = []
        for index, option in enumerate(self._options):
            is_active = index == self._selected_index
            pointer = "▸" if is_active else " "
            pointer_style = "bright_cyan" if is_active else "dim"
            label_style = "bold white" if is_active else "white"
            desc_style = "dim"

            line = Text()
            line.append(pointer, style=pointer_style)
            line.append(f" {option['choice']}. ", style="dim")
            line.append(option["label"], style=label_style)
            description = option.get("description", "")
            if description:
                line.append(" — ", style="dim")
                line.append(description, style=desc_style)
            option_lines.append(line)

        body = Group(header, location, hint, Text(""), *option_lines)

        panel = Panel(
            body,
            title="Approval",
            border_style="bright_cyan",
            padding=(1, 2),
        )

        # Render tool header (persistent) + approval panel (will be cleared after approval)
        conversation.render_approval_prompt([panel], persistent_header=tool_header)
        conversation.scroll_end(animate=False)
