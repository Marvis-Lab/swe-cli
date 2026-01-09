"""Message widgets for ConversationLog with text selection support.

These widgets replace RichLog.write() patterns to enable native Textual text selection.
Each message is a mounted widget that supports click-and-drag text selection.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Markdown, Static
from textual.widgets._markdown import MarkdownStream

from swecli.ui_textual.style_tokens import (
    BLUE_BRIGHT,
    ERROR,
    GREY,
    PRIMARY,
    SUCCESS,
    THINKING_ICON,
    WARNING,
)


class SelectableMarkdown(Markdown):
    """Markdown widget with text selection enabled."""

    can_focus = True  # Allow widget to receive focus and mouse events for selection
    ALLOW_SELECT = True

    @property
    def allow_select(self) -> bool:
        """Override to enable selection regardless of container status."""
        return True


class NoMarkupStatic(Static):
    """Static widget that doesn't interpret Rich markup."""

    can_focus = True  # Allow widget to receive focus and mouse events for selection
    ALLOW_SELECT = True  # Enable text selection on this widget

    @property
    def allow_select(self) -> bool:
        """Override to enable selection regardless of container status."""
        return True

    def __init__(self, content: str = "", **kwargs: Any) -> None:
        super().__init__(content, markup=False, **kwargs)


class NonSelectableStatic(NoMarkupStatic):
    """Static widget that doesn't allow text selection (for UI chrome)."""

    can_focus = False  # UI chrome should not be focusable

    @property
    def allow_select(self) -> bool:
        """Override to disable selection for UI chrome."""
        return False

    @property
    def text_selection(self) -> None:
        return None

    @text_selection.setter
    def text_selection(self, value: Any) -> None:
        pass

    def get_selection(self, selection: Any) -> None:
        return None


class SpinnerWidget(Static):
    """Animated spinner widget matching the original spinner_manager behavior."""

    SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    DEFAULT_CSS = """
    SpinnerWidget {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, message: str = "", tip: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._message = message
        self._tip = tip
        self._spinner_index = 0
        self._started_at = 0.0
        self._timer = None

    def on_mount(self) -> None:
        """Start the spinner animation when mounted."""
        import time
        self._started_at = time.monotonic()
        self._render_frame()
        self._timer = self.set_interval(0.12, self._advance_frame)

    def on_unmount(self) -> None:
        """Stop the timer when unmounted."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _advance_frame(self) -> None:
        """Advance to next spinner frame."""
        self._spinner_index = (self._spinner_index + 1) % len(self.SPINNER_CHARS)
        self._render_frame()

    def _render_frame(self) -> None:
        """Render the current spinner frame."""
        import time
        from rich.text import Text

        elapsed = 0
        if self._started_at:
            elapsed = int(time.monotonic() - self._started_at)

        frame = self.SPINNER_CHARS[self._spinner_index]
        suffix = f" ({elapsed}s)" if elapsed > 0 else ""

        content = Text()
        content.append(frame, style=BLUE_BRIGHT)
        content.append(f" {self._message}{suffix}", style=BLUE_BRIGHT)

        if self._tip:
            content.append("\n  ⎿  Tip: ", style=GREY)
            content.append(self._tip, style=GREY)

        self.update(content)

    def update_message(self, message: str, tip: str = "") -> None:
        """Update the spinner message."""
        self._message = message
        self._tip = tip
        self._render_frame()


class ExpandingBorder(NonSelectableStatic):
    """A border that expands vertically with its container."""

    DEFAULT_CSS = """
    ExpandingBorder {
        width: 1;
        color: #7a7e86;
    }
    """

    def render(self) -> str:
        height = self.size.height
        if height <= 1:
            return "⎣"
        return "\n".join(["⎢"] * (height - 1) + ["⎣"])

    def on_resize(self) -> None:
        self.refresh()


class UserMessage(Static):
    """User message widget with selectable content."""

    DEFAULT_CSS = """
    UserMessage {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }

    .user-message-container {
        width: 100%;
        height: auto;
    }

    .user-message-prompt {
        width: 2;
        height: auto;
        color: #d0d4dc;
        text-style: bold;
    }

    .user-message-content {
        width: 1fr;
        height: auto;
    }
    """

    def __init__(self, content: str, pending: bool = False) -> None:
        super().__init__()
        self.add_class("user-message")
        self._content = content
        self._pending = pending

    def on_mount(self) -> None:
        """Render user message on mount."""
        from rich.text import Text
        content = Text()
        content.append("› ", style=f"bold {PRIMARY}")
        content.append(self._content, style=PRIMARY)
        self.update(content)
        if self._pending:
            self.add_class("pending")

    async def set_pending(self, pending: bool) -> None:
        if pending == self._pending:
            return
        self._pending = pending
        if pending:
            self.add_class("pending")
        else:
            self.remove_class("pending")


class StreamingMessageBase(Static):
    """Base class for messages with streaming markdown content."""

    def __init__(self, content: str = "") -> None:
        super().__init__()
        self._content = content
        self._markdown: Markdown | None = None
        self._stream: MarkdownStream | None = None

    def _get_markdown(self) -> Markdown:
        if self._markdown is None:
            raise RuntimeError(
                "Markdown widget not initialized. compose() must be called first."
            )
        return self._markdown

    def _ensure_stream(self) -> MarkdownStream:
        if self._stream is None:
            self._stream = Markdown.get_stream(self._get_markdown())
        return self._stream

    async def append_content(self, content: str) -> None:
        """Append streaming content to the message."""
        if not content:
            return
        self._content += content
        if self._should_write_content():
            stream = self._ensure_stream()
            await stream.write(content)

    async def write_initial_content(self) -> None:
        """Write the initial content if any."""
        if self._content and self._should_write_content():
            stream = self._ensure_stream()
            await stream.write(self._content)

    async def stop_stream(self) -> None:
        """Stop the streaming and finalize content."""
        if self._stream is None:
            return
        await self._stream.stop()
        self._stream = None

    def _should_write_content(self) -> bool:
        return True

    @property
    def content(self) -> str:
        """Get the full content."""
        return self._content


class AssistantMessage(Static):
    """Assistant message with colored bullet prefix."""

    DEFAULT_CSS = """
    AssistantMessage {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, content: str = "") -> None:
        super().__init__()
        self.add_class("assistant-message")
        self._content = content

    def on_mount(self) -> None:
        """Render the message on mount - identical to UserMessage pattern."""
        from rich.text import Text

        text = Text()
        text.append("● ", style=SUCCESS)
        text.append(self._content, style=PRIMARY)
        self.update(text)

    async def append_content(self, content: str) -> None:
        """Append streaming content to the message."""
        if not content:
            return
        self._content += content
        # Re-render with updated content
        from rich.text import Text

        text = Text()
        text.append("● ", style=SUCCESS)
        text.append(self._content, style=PRIMARY)
        self.update(text)

    async def stop_stream(self) -> None:
        """Stop the streaming (no-op for Static-based rendering)."""
        pass

    def get_text_content(self) -> str:
        """Get the raw text content (without the dot prefix)."""
        return self._content


class ThinkingMessage(Vertical):
    """Thinking/reasoning message with collapsible content."""

    DEFAULT_CSS = """
    ThinkingMessage {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        color: #7a7e86;
    }
    ThinkingMessage > .header-widget {
        width: auto;
        height: auto;
    }
    ThinkingMessage > .content-widget {
        width: 100%;
        height: auto;
        color: #7a7e86;
    }
    ThinkingMessage Markdown {
        color: #7a7e86;
    }
    """

    SPINNING_TEXT = "Thinking"
    COMPLETED_TEXT = "Thought"

    def __init__(self, content: str = "", collapsed: bool = False) -> None:
        super().__init__()
        self.add_class("thinking-message")
        self._content = content
        self.collapsed = collapsed
        self._completed = False
        self._markdown: Markdown | None = None
        self._stream: MarkdownStream | None = None
        self._header_widget: Static | None = None

    def compose(self) -> ComposeResult:
        """Compose the thinking message with header and content widgets."""
        # Create header widget
        self._header_widget = Static("", classes="header-widget")
        yield self._header_widget

        # Create markdown content widget (hidden if collapsed)
        self._markdown = SelectableMarkdown("")
        self._markdown.add_class("content-widget")
        self._markdown.display = not self.collapsed
        yield self._markdown

    def on_mount(self) -> None:
        """Initialize the thinking message on mount."""
        self._render_header()

    def _render_header(self) -> None:
        """Render the header with icon and label."""
        from rich.text import Text
        header = Text()
        header.append(f"{THINKING_ICON} ", style=GREY)
        label = self.COMPLETED_TEXT if self._completed else self.SPINNING_TEXT
        header.append(label, style=f"italic {GREY}")
        triangle = " ▶" if self.collapsed else " ▼"
        header.append(triangle, style=GREY)
        if self._header_widget is not None:
            self._header_widget.update(header)

    def _ensure_markdown(self) -> Markdown:
        """Get the markdown widget."""
        if self._markdown is None:
            # Fallback if compose hasn't run yet
            self._markdown = SelectableMarkdown("")
            self._markdown.add_class("content-widget")
            self._markdown.display = not self.collapsed
            self.mount(self._markdown)
        return self._markdown

    def _ensure_stream(self) -> MarkdownStream:
        if self._stream is None:
            self._stream = Markdown.get_stream(self._ensure_markdown())
        return self._stream

    async def append_content(self, content: str) -> None:
        """Append streaming content to the message."""
        if not content:
            return
        self._content += content
        if not self.collapsed:
            stream = self._ensure_stream()
            await stream.write(content)

    async def write_initial_content(self) -> None:
        """Write the initial content if any."""
        if self._content and not self.collapsed:
            stream = self._ensure_stream()
            await stream.write(self._content)

    async def stop_stream(self) -> None:
        """Stop the streaming and finalize content."""
        if self._stream is None:
            return
        await self._stream.stop()
        self._stream = None

    def set_completed(self) -> None:
        """Mark thinking as completed."""
        self._completed = True
        self._render_header()

    async def on_click(self) -> None:
        await self.toggle_collapsed()

    async def toggle_collapsed(self) -> None:
        await self.set_collapsed(not self.collapsed)

    async def set_collapsed(self, collapsed: bool) -> None:
        if self.collapsed == collapsed:
            return
        self.collapsed = collapsed
        # Re-render header with new triangle direction
        self._render_header()
        if self._markdown:
            self._markdown.display = not collapsed
            if not collapsed and self._content:
                # Re-render content when expanding
                if self._stream is not None:
                    await self._stream.stop()
                    self._stream = None
                await self._markdown.update("")
                stream = self._ensure_stream()
                await stream.write(self._content)

    def _should_write_content(self) -> bool:
        return not self.collapsed


class SystemMessage(Static):
    """System message with muted styling."""

    DEFAULT_CSS = """
    SystemMessage {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        color: #7a7e86;
        text-style: italic;
    }
    """

    def __init__(self, content: str) -> None:
        super().__init__(content)
        self.add_class("system-message")


class ErrorMessage(Static):
    """Error message with red styling."""

    DEFAULT_CSS = """
    ErrorMessage {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, error: str, collapsed: bool = False) -> None:
        super().__init__()
        self.add_class("error-message")
        self._error = error
        self.collapsed = collapsed

    def on_mount(self) -> None:
        """Render error message on mount."""
        self._render_content()

    def _render_content(self) -> None:
        """Render the error content."""
        from rich.text import Text
        content = Text()
        content.append("⦿ ", style=ERROR)
        text = "Error. (click to expand)" if self.collapsed else self._error
        content.append(text, style=ERROR)
        self.update(content)

    async def on_click(self) -> None:
        self.set_collapsed(not self.collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        if self.collapsed == collapsed:
            return
        self.collapsed = collapsed
        self._render_content()


class WarningMessage(Static):
    """Warning message widget."""

    DEFAULT_CSS = """
    WarningMessage {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, message: str, show_border: bool = True) -> None:
        super().__init__()
        self.add_class("warning-message")
        self._message = message
        self._show_border = show_border

    def on_mount(self) -> None:
        """Render warning message on mount."""
        from rich.text import Text
        content = Text()
        if self._show_border:
            content.append("│ ", style=WARNING)
        content.append(self._message, style=WARNING)
        self.update(content)


class ToolCallMessage(Static):
    """Tool call display widget with animated spinner."""

    DEFAULT_CSS = """
    ToolCallMessage {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, tool_name: str, description: str = "") -> None:
        super().__init__()
        self.add_class("tool-call-message")
        self._tool_name = tool_name
        self._description = description
        self._status: str = "pending"  # pending, running, success, error
        self._started_at = 0.0
        self._timer = None

    def on_mount(self) -> None:
        """Start with pending state."""
        self._render_content()

    def on_unmount(self) -> None:
        """Stop timer when unmounted."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _render_content(self) -> None:
        """Render the tool call content."""
        import time
        from rich.text import Text

        content = Text()

        if self._status == "pending":
            content.append("⏺ ", style=SUCCESS)
        elif self._status == "running":
            elapsed = 0
            if self._started_at:
                elapsed = int(time.monotonic() - self._started_at)
            content.append("⏺ ", style=SUCCESS)
            content.append(self._tool_name, style=GREY)
            content.append(f" ({elapsed}s)", style=GREY)
            self.update(content)
            return
        elif self._status == "success":
            content.append("✓ ", style=SUCCESS)
        elif self._status == "error":
            content.append("✗ ", style=ERROR)

        content.append(self._tool_name, style=GREY)

        if self._status in ("success", "error") and self._started_at:
            import time
            elapsed = int(time.monotonic() - self._started_at)
            content.append(f" ({elapsed}s)", style=GREY)

        self.update(content)

    def set_running(self) -> None:
        """Mark tool as running with animation."""
        import time
        self._status = "running"
        self._started_at = time.monotonic()
        self._render_content()
        self._timer = self.set_interval(1.0, self._render_content)

    def set_success(self) -> None:
        """Mark tool as completed successfully."""
        self._status = "success"
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._render_content()

    def set_error(self) -> None:
        """Mark tool as failed."""
        self._status = "error"
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._render_content()


class ToolResultMessage(Static):
    """Tool result display widget."""

    DEFAULT_CSS = """
    ToolResultMessage {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, result: str, show_prefix: bool = True) -> None:
        super().__init__()
        self.add_class("tool-result-message")
        self._result = result
        self._show_prefix = show_prefix

    def on_mount(self) -> None:
        """Render content on mount."""
        from rich.text import Text

        content = Text()
        if self._show_prefix:
            # Match original format: "  ⎿  " (2 spaces + arrow + 2 spaces)
            content.append("  ⎿  ", style=GREY)
        else:
            # Continuation lines: 7 spaces for alignment
            content.append("       ", style=GREY)
        content.append(self._result, style=GREY)
        self.update(content)


class BashOutputMessage(Static):
    """Bash command output display widget."""

    DEFAULT_CSS = """
    BashOutputMessage {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }

    .bash-output-container {
        width: 100%;
        height: auto;
    }

    .bash-cwd-line {
        width: 100%;
        height: auto;
    }

    .bash-cwd {
        height: auto;
        color: #7a7e86;
    }

    .bash-cwd-spacer {
        width: 1fr;
        height: auto;
    }

    .bash-exit-success {
        height: auto;
        color: #6ad18f;
    }

    .bash-exit-failure {
        height: auto;
        color: #ff5c57;
    }

    .bash-exit-code {
        height: auto;
        color: #ff5c57;
    }

    .bash-command-line {
        width: 100%;
        height: auto;
    }

    .bash-chevron {
        width: 2;
        height: auto;
        color: #d0d4dc;
    }

    .bash-command {
        height: auto;
        color: #d0d4dc;
    }

    .bash-command-spacer {
        width: 1fr;
        height: auto;
    }

    .bash-output {
        width: 100%;
        height: auto;
        padding-left: 2;
    }
    """

    def __init__(
        self, command: str, cwd: str, output: str, exit_code: int
    ) -> None:
        super().__init__()
        self.add_class("bash-output-message")
        self._command = command
        self._cwd = cwd
        self._output = output
        self._exit_code = exit_code

    def compose(self) -> ComposeResult:
        with Vertical(classes="bash-output-container"):
            with Horizontal(classes="bash-cwd-line"):
                yield NoMarkupStatic(self._cwd, classes="bash-cwd")
                yield NoMarkupStatic("", classes="bash-cwd-spacer")
                if self._exit_code == 0:
                    yield NoMarkupStatic("✓", classes="bash-exit-success")
                else:
                    yield NoMarkupStatic("✗", classes="bash-exit-failure")
                    yield NoMarkupStatic(
                        f" ({self._exit_code})", classes="bash-exit-code"
                    )
            with Horizontal(classes="bash-command-line"):
                yield NoMarkupStatic("> ", classes="bash-chevron")
                yield NoMarkupStatic(self._command, classes="bash-command")
                yield NoMarkupStatic("", classes="bash-command-spacer")
            if self._output:
                yield NoMarkupStatic(self._output, classes="bash-output")


class InterruptMessage(Static):
    """Interrupt notification widget."""

    DEFAULT_CSS = """
    InterruptMessage {
        width: 100%;
        height: auto;
        margin: 1 0;
    }

    .interrupt-container {
        width: 100%;
        height: auto;
    }

    .interrupt-border {
        width: 1;
        height: auto;
        color: #ffb347;
    }

    .interrupt-content {
        width: 1fr;
        height: auto;
        padding-left: 1;
        color: #ffb347;
    }
    """

    def __init__(self, message: str = "Interrupted · What should I do instead?") -> None:
        super().__init__()
        self.add_class("interrupt-message")
        self._message = message

    def on_mount(self) -> None:
        """Render interrupt message on mount."""
        from rich.text import Text
        content = Text()
        content.append("│ ", style=WARNING)
        content.append(self._message, style=WARNING)
        self.update(content)
