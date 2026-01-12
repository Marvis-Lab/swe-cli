"""Textual-based chat application for SWE-CLI - POC."""

import threading
from typing import Any, Callable, Mapping, Optional

from prompt_toolkit.completion import Completer

from rich.console import RenderableType
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.widgets import Header, Rule, Static

from swecli.ui_textual.widgets import ConversationLog
from swecli.ui_textual.widgets.chat_text_area import ChatTextArea
from swecli.ui_textual.widgets.status_bar import ModelFooter, StatusBar
from swecli.ui_textual.widgets.todo_panel import TodoPanel
from swecli.ui_textual.components import TipsManager
from swecli.ui_textual.controllers.approval_prompt_controller import ApprovalPromptController
from swecli.ui_textual.controllers.autocomplete_popup_controller import AutocompletePopupController
from swecli.ui_textual.controllers.command_router import CommandRouter
from swecli.ui_textual.controllers.message_controller import MessageController
from swecli.ui_textual.controllers.model_picker_controller import ModelPickerController
from swecli.ui_textual.controllers.spinner_controller import SpinnerController
from swecli.ui_textual.managers.console_buffer_manager import ConsoleBufferManager
from swecli.ui_textual.managers.message_history import MessageHistory
from swecli.ui_textual.managers.tool_summary_manager import ToolSummaryManager
from swecli.ui_textual.managers.spinner_service import SpinnerService
from swecli.ui_textual.renderers.welcome_panel import render_welcome_panel



class SWECLIChatApp(App):
    """SWE-CLI Chat Application using Textual."""

    CSS_PATH = "styles/chat.tcss"

    # Disable mouse to avoid escape sequence issues and random character input
    ENABLE_MOUSE = False

    BINDINGS = [
        Binding("ctrl+c", "clear_or_quit", "", show=False, priority=True),
        Binding("ctrl+l", "clear_conversation", "", show=False),
        Binding("ctrl+t", "toggle_todo_panel", "Toggle Todos", show=False),
        Binding("ctrl+shift+t", "toggle_thinking", "Thinking", show=False),
        Binding("escape", "interrupt", "", show=False),
        Binding("pageup", "scroll_up", "Scroll Up", show=False),
        Binding("pagedown", "scroll_down", "Scroll Down", show=False),
        Binding("up", "scroll_up_line", "Scroll Up One Line", show=False),
        Binding("down", "scroll_down_line", "Scroll Down One Line", show=False),
        Binding("ctrl+up", "focus_conversation", "Focus Conversation", show=False),
        Binding("ctrl+down", "focus_input", "Focus Input", show=False),
        Binding("shift+tab", "cycle_mode", "Switch Mode"),
        Binding("ctrl+shift+a", "cycle_autonomy", "Autonomy", show=False),
    ]

    def __init__(
        self,
        on_message: Optional[Callable[[str], None]] = None,
        model: str = "claude-sonnet-4",
        model_slots: Mapping[str, tuple[str, str]] | None = None,
        on_cycle_mode: Optional[Callable[[], str]] = None,
        completer: Optional[Completer] = None,
        on_model_selected: Optional[Callable[[str, str, str], Any]] = None,
        get_model_config: Optional[Callable[[], Mapping[str, Any]]] = None,
        on_ready: Optional[Callable[[], None]] = None,
        on_interrupt: Optional[Callable[[], bool]] = None,
        working_dir: Optional[str] = None,
        todo_handler: Optional[Any] = None,
        **kwargs,
    ):
        """Initialize chat application.

        Args:
            on_message: Callback for when user sends a message
            model: Model name to display in status bar
            model_slots: Mapping of model slots (normal/thinking/vision) to human-readable values
            completer: Autocomplete provider for slash commands and @ mentions
            on_model_selected: Callback invoked after a model is selected
            get_model_config: Callback returning current model configuration details
            on_ready: Callback invoked once the UI finishes its first layout pass
            on_interrupt: Callback for when user presses ESC to interrupt
            working_dir: Working directory path for repo display
            todo_handler: TodoHandler instance for managing todos
        """
        # Set color system to inherit from terminal
        kwargs.setdefault("ansi_color", "auto")
        super().__init__(**kwargs)
        self.on_message = on_message
        self.on_cycle_mode = on_cycle_mode
        self.on_interrupt = on_interrupt
        self.model = model
        self.completer = completer
        self.model_slots = dict(model_slots or {})
        self.on_model_selected = on_model_selected
        self.get_model_config = get_model_config
        self._on_ready = on_ready
        self.working_dir = working_dir or ""
        self.todo_handler = todo_handler
        self.autocomplete_popup: Static | None = None
        self._autocomplete_controller: AutocompletePopupController | None = None
        self.footer: ModelFooter | None = None
        self._is_processing = False
        self._last_assistant_lines: set[str] = set()
        self._last_rendered_assistant: str | None = None
        self._last_assistant_normalized: str | None = None
        self._buffer_console_output = False
        self._pending_assistant_normalized: str | None = None
        self._ui_thread: threading.Thread | None = None
        self._tips_manager = TipsManager()
        self._model_picker: ModelPickerController = ModelPickerController(self)
        self._approval_controller = ApprovalPromptController(self)
        self._spinner = SpinnerController(self, self._tips_manager, todo_handler=self.todo_handler)
        self.spinner_service = SpinnerService(self)
        self._console_buffer = ConsoleBufferManager(self)
        self._queued_console_renderables = self._console_buffer._queue
        self._tool_summary = ToolSummaryManager(self)
        self._command_router = CommandRouter(self)
        self._history = MessageHistory()
        self._message_controller = MessageController(self)
        self._exit_confirmation_mode = False
        self._selection_tip_timer: Any | None = None
        self._default_label = "› Type your message (Enter to send, Shift+Enter for new line):"
        self._thinking_visible = False  # Thinking mode visibility state (default OFF)

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header(show_clock=True)

        with Container(id="main-container"):
            # Conversation area
            yield ConversationLog(id="conversation")

            # Separator line between conversation and input
            yield Rule(line_style="solid")

            # Todo panel (persistent, toggleable with Ctrl+T)
            yield TodoPanel(todo_handler=self.todo_handler, id="todo-panel")

            # Input area
            with Vertical(id="input-container"):
                yield Static(
                    "› Type your message (Enter to send, Shift+Enter for new line):",
                    id="input-label",
                )
                yield ChatTextArea(
                    id="input",
                    placeholder="Type your message...",
                    soft_wrap=True,
                    completer=self.completer,
                )

            # Status bar
            yield StatusBar(model=self.model, working_dir=self.working_dir, id="status-bar")

        yield ModelFooter(self.model_slots, normal_model=self.model, id="model-footer")

    def on_mount(self) -> None:
        """Initialize the app on mount."""

        self._ui_thread = threading.current_thread()

        # Get widgets
        self.conversation = self.query_one("#conversation", ConversationLog)
        self.input_field = self.query_one("#input", ChatTextArea)
        self.input_label = self.query_one("#input-label", Static)
        input_container = self.query_one("#input-container")
        self.status_bar = self.query_one("#status-bar", StatusBar)
        self.footer = self.query_one("#model-footer", ModelFooter)

        # Inject SpinnerService into TodoPanel (uses callback API for arrow spinner)
        try:
            todo_panel = self.query_one("#todo-panel", TodoPanel)
            todo_panel.set_spinner_service(self.spinner_service)
        except Exception:
            pass  # TodoPanel might not exist

        self.input_field.set_completer(self.completer)
        self.autocomplete_popup = Static("", id="autocomplete-popup")
        self.autocomplete_popup.can_focus = False
        self.autocomplete_popup.styles.display = "none"
        input_container.mount(self.autocomplete_popup)
        self._autocomplete_controller = AutocompletePopupController(self.autocomplete_popup)
        self.update_autocomplete([], None)

        # Focus input field
        self.input_field.focus()

        # Show different welcome message based on whether we have real backend integration
        if self.on_message:
            self.title = "SWE-CLI Chat"
            self.sub_title = "AI-powered coding assistant"
            render_welcome_panel(self.conversation, real_integration=True)
        else:
            self.title = "SWE-CLI Chat (Textual POC)"
            self.sub_title = "Full-screen terminal interface"
            render_welcome_panel(self.conversation, real_integration=False)

        if self._on_ready is not None:
            self.call_after_refresh(self._on_ready)

    def update_model_slots(self, model_slots: Mapping[str, tuple[str, str]] | None) -> None:
        """Update footer model display with new slot information."""
        self.model_slots = dict(model_slots or {})
        if self.footer is not None:
            self.footer.update_models(self.model_slots)

    def update_primary_model(self, model: str) -> None:
        """Update the primary model label shown in the status bar and footer."""
        self.model = model
        if hasattr(self, "status_bar"):
            self.status_bar.set_model_name(model)
        # Also update the footer to show the normal model
        if hasattr(self, "footer"):
            self.footer.set_normal_model(model)


    def update_autocomplete(
        self,
        entries: list[tuple[str, str]],
        selected_index: int | None = None,
    ) -> None:
        """Render autocomplete options directly beneath the input field."""

        controller = self._autocomplete_controller
        if controller is None:
            return

        if self._approval_controller.active:
            controller.reset()
            return

        controller.render(entries, selected_index)


    def _start_local_spinner(self, message: str | None = None) -> None:
        """Begin local spinner animation while backend processes."""

        if hasattr(self, "_console_buffer"):
            self._console_buffer.clear()
        self._spinner.start(message)

    def _stop_local_spinner(self) -> None:
        """Stop spinner animation and clear indicators."""

        self._spinner.stop()
        if hasattr(self, "_console_buffer"):
            self._console_buffer.clear_assistant_history()
            self._console_buffer.flush()
        self.flush_console_buffer()

    def resume_reasoning_spinner(self) -> None:
        """Restart the thinking spinner after tool output while waiting for reply."""

        if not self._is_processing:
            return

        self._stop_local_spinner()
        self._start_local_spinner()

    def flush_console_buffer(self) -> None:
        """Flush queued console renderables after assistant message is recorded."""

        if hasattr(self, "_console_buffer"):
            self._console_buffer.flush()

    def start_console_buffer(self) -> None:
        """Begin buffering console output to avoid interleaving with spinner."""

        self._buffer_console_output = True
        if hasattr(self, "_console_buffer"):
            self._console_buffer.start()

    def stop_console_buffer(self) -> None:
        """Stop buffering console output and flush any pending items."""

        self._buffer_console_output = False
        if hasattr(self, "_console_buffer"):
            self._console_buffer.stop()

    @staticmethod
    def _normalize_assistant_line(line: str) -> str:
        return ConsoleBufferManager._normalize_line(line)

    @staticmethod
    def _normalize_paragraph(text: str) -> str:
        return ConsoleBufferManager._normalize_paragraph(text)

    def _should_suppress_renderable(self, renderable: RenderableType) -> bool:
        if hasattr(self, "_console_buffer"):
            return self._console_buffer.should_suppress(renderable)
        return False

    def render_console_output(self, renderable: RenderableType) -> None:
        """Render console output, buffering if spinner is active."""

        if hasattr(self, "_console_buffer"):
            self._console_buffer.enqueue_or_write(renderable)
        elif hasattr(self, "conversation"):
            self.conversation.write(renderable)


    def record_assistant_message(self, message: str) -> None:
        """Track assistant lines to suppress duplicate console echoes."""

        if hasattr(self, "_console_buffer"):
            self._console_buffer.record_assistant_message(message)
        if hasattr(self, "_tool_summary"):
            self._tool_summary.on_assistant_message(message)

    async def action_send_message(self) -> None:
        """Send message when user presses Enter."""
        await self._message_controller.submit(self.input_field.text)

    async def on_chat_text_area_submitted(self, event: ChatTextArea.Submitted) -> None:
        """Handle chat submissions from the custom text area."""
        await self._message_controller.submit(event.value)

    def add_assistant_message(self, message: str) -> None:
        """Proxy to conversation helper for compatibility with approval manager."""
        if hasattr(self, "conversation"):
            self.conversation.add_assistant_message(message)

    def add_system_message(self, message: str) -> None:
        """Proxy system message helper."""
        if hasattr(self, "conversation"):
            self.conversation.add_system_message(message)

    async def handle_command(self, command: str) -> bool:
        """Handle slash commands.

        Returns True if the command was handled locally, False to allow higher-level
        handlers (e.g., REPL runner) to process it.
        """
        handled = await self._command_router.handle(command)
        if not handled and not self.on_message:
            cmd = command.lower().split()[0]
            self.conversation.add_error(f"Unknown command: {cmd}")
        return handled

    async def _start_model_picker(self) -> None:
        """Launch the in-conversation model picker flow."""
        await self._model_picker.start()

    def _model_picker_move(self, delta: int) -> None:
        self._model_picker.move(delta)

    def _model_picker_back(self) -> None:
        self._model_picker.back()

    def _model_picker_cancel(self) -> None:
        self._model_picker.cancel()

    async def _model_picker_confirm(self) -> None:
        await self._model_picker.confirm()

    async def _handle_model_picker_input(self, raw_value: str) -> bool:
        return await self._model_picker.handle_input(raw_value)

    async def show_approval_modal(self, command: str, working_dir: str) -> tuple[bool, str, str]:
        """Display an inline approval prompt inside the conversation log."""
        return await self._approval_controller.start(command, working_dir)

    def _render_approval_prompt(self) -> None:
        self._approval_controller.render()

    def _approval_move(self, delta: int) -> None:
        self._approval_controller.move(delta)

    def _approval_confirm(self) -> None:
        self._approval_controller.confirm()

    def _approval_cancel(self) -> None:
        self._approval_controller.cancel()

    async def process_message(self, message: str) -> None:
        """Send the user message to the backend for processing."""
        await self._message_controller.process(message)

    def _set_processing_state(self, active: bool) -> None:
        """Update internal processing state and status bar indicator."""
        self._message_controller.set_processing_state(active)

    def record_tool_summary(
        self, tool_name: str, tool_args: dict[str, Any], result_lines: list[str]
    ) -> None:
        """Record a tool result summary for fallback assistant messaging."""
        if hasattr(self, "_tool_summary"):
            self._tool_summary.record_summary(tool_name, tool_args, result_lines)

    def _emit_tool_follow_up_if_needed(self) -> None:
        """Render a fallback assistant follow-up if tools finished without LLM wrap-up."""
        if hasattr(self, "_tool_summary"):
            self._tool_summary.emit_follow_up_if_needed()

    @property
    def _pending_tool_summaries(self) -> list[str]:
        if hasattr(self, "_tool_summary"):
            return self._tool_summary._pending
        return []

    @_pending_tool_summaries.setter
    def _pending_tool_summaries(self, value: list[str]) -> None:
        if hasattr(self, "_tool_summary"):
            self._tool_summary._pending = list(value)

    @property
    def _assistant_response_received(self) -> bool:
        if hasattr(self, "_tool_summary"):
            return self._tool_summary._assistant_response_received
        return False

    @_assistant_response_received.setter
    def _assistant_response_received(self, value: bool) -> None:
        if hasattr(self, "_tool_summary"):
            self._tool_summary._assistant_response_received = value

    @property
    def _saw_tool_result(self) -> bool:
        if hasattr(self, "_tool_summary"):
            return self._tool_summary._saw_tool_result
        return False

    @_saw_tool_result.setter
    def _saw_tool_result(self, value: bool) -> None:
        if hasattr(self, "_tool_summary"):
            self._tool_summary._saw_tool_result = value

    def notify_processing_complete(self) -> None:
        """Reset processing indicators once backend work completes."""
        self._message_controller.notify_processing_complete()

    def notify_processing_error(self, error: str) -> None:
        """Display an error message and reset processing indicators."""
        self._message_controller.notify_processing_error(error)

    def action_clear_conversation(self) -> None:
        """Clear the conversation (Ctrl+L)."""
        self.conversation.clear()
        self.conversation.add_system_message("Conversation cleared (Ctrl+L)")

    def action_interrupt(self) -> None:
        """Interrupt processing (ESC)."""
        if self._is_processing:
            # Call interrupt callback if provided
            if self.on_interrupt:
                self.on_interrupt()
            # Don't display system message here - let the tool result formatter handle it
            # This prevents duplicate "Processing interrupted" messages

    def action_clear_or_quit(self) -> None:
        """Clear input text or quit (Ctrl+C).

        First Ctrl+C: Clear input (if any) + show exit confirmation
        Second Ctrl+C: Quit the application
        """
        # If already in exit confirmation mode, quit
        if self._exit_confirmation_mode:
            self.exit()
            return

        # Clear input if there's text
        if self.input_field.text.strip():
            self.input_field.clear()

        # Enter exit confirmation mode
        self._exit_confirmation_mode = True
        self.input_label.update("› Press Ctrl+C again to quit")

    def _cancel_exit_confirmation(self) -> None:
        """Cancel exit confirmation and restore normal state."""
        if self._exit_confirmation_mode:
            self._exit_confirmation_mode = False
            self.input_label.update("› Type your message (Enter to send, Shift+Enter for new line):")

    def update_queue_indicator(self, queue_size: int) -> None:
        """Update input label to show queue status.

        Args:
            queue_size: Number of messages waiting in queue
        """
        # Don't override exit confirmation message
        if self._exit_confirmation_mode:
            return

        if queue_size > 0:
            msg = "message" if queue_size == 1 else "messages"
            self.input_label.update(f"› {queue_size} {msg} queued")
        else:
            self.input_label.update("› Type your message (Enter to send, Shift+Enter for new line):")

    def show_selection_tip(self) -> None:
        """Show temporary tip for text selection."""
        # Don't override exit confirmation message
        if self._exit_confirmation_mode:
            return

        # Cancel existing timer if any
        if self._selection_tip_timer:
            self._selection_tip_timer.stop()

        self.input_label.update("› 💡 Shift+drag (or Option+drag on Mac) to select text")
        self._selection_tip_timer = self.set_timer(4, self._revert_input_label)

    def _revert_input_label(self) -> None:
        """Revert input label to default."""
        if self._exit_confirmation_mode:
            return

        self.input_label.update(self._default_label)
        self._selection_tip_timer = None

    def action_quit(self) -> None:
        """Quit the application (Ctrl+C)."""
        # Stop all spinners before exiting
        if hasattr(self, 'spinner_service'):
            self.spinner_service.stop_all(immediate=True)
        self.exit()

    def action_scroll_up(self) -> None:
        """Scroll conversation up (Page Up)."""
        self.conversation.scroll_partial_page(direction=-1)

    def action_scroll_down(self) -> None:
        """Scroll conversation down (Page Down)."""
        self.conversation.scroll_partial_page(direction=1)

    def action_scroll_up_line(self) -> None:
        """Scroll conversation up one line (Up Arrow)."""
        # Only scroll if conversation has focus, otherwise let input handle it
        if self.conversation.has_focus:
            self.conversation.scroll_up()
        elif not self.input_field.has_focus:
            # If nothing focused, scroll conversation anyway
            self.conversation.scroll_up()

    def action_scroll_down_line(self) -> None:
        """Scroll conversation down one line (Down Arrow)."""
        # Only scroll if conversation has focus, otherwise let input handle it
        if self.conversation.has_focus:
            self.conversation.scroll_down()
        elif not self.input_field.has_focus:
            # If nothing focused, scroll conversation anyway
            self.conversation.scroll_down()

    def action_focus_conversation(self) -> None:
        """Focus the conversation area for scrolling (Ctrl+Up)."""
        self.conversation.focus()
        self.conversation.add_system_message(
            "📜 Conversation focused - use arrow keys or trackpad to scroll"
        )

    def action_focus_input(self) -> None:
        """Focus the input field for typing (Ctrl+Down)."""
        self.input_field.focus()

    def action_history_up(self) -> None:
        """Navigate backward through previously submitted messages."""

        if not hasattr(self, '_history'):
            return

        result = self._history.navigate_up(self.input_field.text)
        if result is None:
            return

        self.input_field.load_text(result)
        self.input_field.move_cursor_to_end()


    def action_history_down(self) -> None:
        """Navigate forward through history or restore unsent input."""

        if not hasattr(self, '_history'):
            return

        result = self._history.navigate_down()
        if result is None:
            return

        self.input_field.load_text(result)
        self.input_field.move_cursor_to_end()

    def action_cycle_mode(self) -> None:
        """Cycle between PLAN and NORMAL modes (Shift+Tab)."""

        if not self.on_cycle_mode:
            return

        try:
            new_mode = self.on_cycle_mode()
        except Exception:  # pragma: no cover - defensive
            return

        if not new_mode:
            return

        mode_label = new_mode.lower()
        self.status_bar.set_mode(mode_label)

    def action_cycle_autonomy(self) -> None:
        """Cycle through autonomy levels: Manual -> Semi-Auto -> Auto (Shift+A)."""
        levels = ["Manual", "Semi-Auto", "Auto"]
        current = self.status_bar.autonomy
        try:
            next_idx = (levels.index(current) + 1) % len(levels)
        except ValueError:
            next_idx = 0
        new_level = levels[next_idx]
        self.status_bar.set_autonomy(new_level)

        # Update approval manager if available
        if hasattr(self, "_approval_manager"):
            self._approval_manager.set_autonomy_level(new_level)

    def action_toggle_todo_panel(self) -> None:
        """Toggle todo panel visibility (Ctrl+T)."""
        try:
            panel = self.query_one("#todo-panel", TodoPanel)
            panel.toggle_expansion()
        except Exception:  # pragma: no cover - defensive
            pass

    def action_toggle_thinking(self) -> None:
        """Toggle thinking content visibility (Ctrl+Shift+T).

        Toggles whether thinking blocks from the think tool are displayed.
        When hidden, thinking content is still captured but not shown.
        Also syncs with tool_registry.thinking_handler for prompt injection.
        """
        # Toggle the app's thinking visibility state
        self._thinking_visible = not self._thinking_visible

        # Sync with thinking handler (used by query_processor for prompt injection)
        if hasattr(self, '_thinking_handler') and self._thinking_handler:
            self._thinking_handler._visible = self._thinking_visible

        # Update status bar
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.set_thinking_enabled(self._thinking_visible)
        except Exception:  # pragma: no cover - defensive
            pass


def create_chat_app(
    on_message: Optional[Callable[[str], None]] = None,
    model: str = "claude-sonnet-4",
    model_slots: Mapping[str, tuple[str, str]] | None = None,
    on_cycle_mode: Optional[Callable[[], str]] = None,
    completer: Optional[Completer] = None,
    on_model_selected: Optional[Callable[[str, str, str], Any]] = None,
    get_model_config: Optional[Callable[[], Mapping[str, Any]]] = None,
    on_ready: Optional[Callable[[], None]] = None,
    on_interrupt: Optional[Callable[[], bool]] = None,
    working_dir: Optional[str] = None,
    todo_handler: Optional[Any] = None,
) -> SWECLIChatApp:
    """Create and return a new chat application instance.

    Args:
        on_message: Optional callback for message processing
        model: Model name to display in status bar
        model_slots: Mapping of model slots to formatted provider/model names
        completer: Autocomplete provider for @ mentions and slash commands
        on_model_selected: Callback invoked after a model is selected
        get_model_config: Callback returning current model configuration details
        on_ready: Callback invoked once the UI completes its first render pass
        on_interrupt: Callback for when user presses ESC to interrupt
        working_dir: Working directory path for repo display
        todo_handler: TodoHandler instance for managing todos

    Returns:
        Configured SWECLIChatApp instance
    """
    return SWECLIChatApp(
        on_message=on_message,
        model=model,
        model_slots=model_slots,
        on_cycle_mode=on_cycle_mode,
        completer=completer,
        on_model_selected=on_model_selected,
        get_model_config=get_model_config,
        on_ready=on_ready,
        on_interrupt=on_interrupt,
        working_dir=working_dir,
        todo_handler=todo_handler,
    )


if __name__ == "__main__":
    # Run standalone for testing
    def handle_message(text: str):
        # Callback for external message handling
        # Don't print here - it will interfere with the UI!
        pass

    app = create_chat_app(on_message=handle_message)
    # Run in application mode (full screen with alternate screen buffer)
    # This is the default behavior when inline is not specified
    app.run()
