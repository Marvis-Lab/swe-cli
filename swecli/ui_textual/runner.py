"""Entry point helper for launching the Textual chat UI alongside core SWE-CLI services."""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import os
import sys
from pathlib import Path
from typing import Callable, Optional


def _reset_terminal_mouse_mode() -> None:
    """Send escape sequences to disable mouse tracking.

    This ensures mouse mode is properly cleaned up even if the app
    crashes or exits unexpectedly. Registered with atexit for reliability.
    """
    try:
        # Disable SGR mouse mode and basic mouse tracking
        sys.stdout.write("\033[?1006l")  # Disable SGR extended mouse mode
        sys.stdout.write("\033[?1003l")  # Disable any-event tracking
        sys.stdout.write("\033[?1002l")  # Disable button-event tracking
        sys.stdout.write("\033[?1000l")  # Disable basic mouse mode
        sys.stdout.flush()
    except Exception:
        pass  # Ignore errors during cleanup


# Register cleanup to run on exit
atexit.register(_reset_terminal_mouse_mode)


from swecli.core.agents.components import extract_plan_from_response
from swecli.core.runtime import ConfigManager, OperationMode
from swecli.core.context_engineering.history import SessionManager
from swecli.models.message import ChatMessage, Role
from swecli.repl.repl import REPL
from swecli.ui_textual.managers.approval_manager import ChatApprovalManager
from swecli.ui_textual.chat_app import create_chat_app
from swecli.ui_textual.runner_components import (
    HistoryHydrator,
    ToolRenderer,
    ModelConfigManager,
    CommandRouter,
    MessageProcessor,
    ConsoleBridge,
    MCPController,
)

# Approval phrases for plan execution
PLAN_APPROVAL_PHRASES = {
    "yes",
    "approve",
    "execute",
    "go ahead",
    "do it",
    "proceed",
    "start",
    "run",
    "ok",
    "okay",
    "y",
    "sure",
    "go",
}


class TextualRunner:
    """Orchestrates the Textual chat UI with the core SWE-CLI runtime.

    This class serves as the main entry point and controller for the UI-based
    interaction mode. It coordinates:

    1. **Core Runtime**: REPL, ConfigManager, SessionManager
    2. **UI Components**: Textual App, History Hydration, Tool Rendering
    3. **Background Services**: Message Processing, Console Bridging, MCP Auto-connect

    The runner manages the lifecycle of the Textual application (`create_chat_app`)
    and bridges standard I/O (console print/logs) into the UI conversation log.

    Usage:
        runner = TextualRunner(working_dir=Path("."))
        runner.run()
    """

    def __init__(
        self,
        *,
        working_dir: Optional[Path] = None,
        repl: Optional[REPL] = None,
        config_manager: Optional[ConfigManager] = None,
        session_manager: Optional[SessionManager] = None,
        auto_connect_mcp: bool = False,
        continue_session: bool = False,
        resume_session_id: Optional[str] = None,
        initial_message: Optional[str] = None,
        dangerously_skip_permissions: bool = False,
    ) -> None:
        self.working_dir = Path(working_dir or Path.cwd()).resolve()
        self._initial_message = initial_message
        self._dangerously_skip_permissions = dangerously_skip_permissions

        # 1. Setup Core Runtime (Config, REPL, Session)
        self._setup_runtime(
            repl=repl,
            config_manager=config_manager,
            session_manager=session_manager,
            auto_connect_mcp=auto_connect_mcp,
            continue_session=continue_session,
            resume_session_id=resume_session_id,
        )

        # 2. Initialize session debug logger (when --verbose)
        self._init_debug_logger()

        # 3. Setup Runner Components
        self._setup_components(auto_connect_mcp)

        # 4. Setup Textual App
        self._setup_app()

        # 5. Finalize
        self._loop = asyncio.new_event_loop()
        self._console_task: asyncio.Task[None] | None = None
        self._queue_update_callback: Callable[[int], None] | None = getattr(
            self.app, "update_queue_indicator", None
        )

    def _setup_runtime(
        self,
        repl: Optional[REPL],
        config_manager: Optional[ConfigManager],
        session_manager: Optional[SessionManager],
        auto_connect_mcp: bool,
        continue_session: bool = False,
        resume_session_id: Optional[str] = None,
    ) -> None:
        """Initialize the core SWE-CLI runtime (REPL, Config, Session)."""
        if repl is not None:
            self.repl = repl
            self.config_manager = config_manager or getattr(
                repl, "config_manager", ConfigManager(self.working_dir)
            )
            self.config = getattr(repl, "config", None) or self.config_manager.get_config()
            self.session_manager = session_manager or getattr(repl, "session_manager", None)

            if self.session_manager is None:
                raise ValueError("SessionManager is required when providing a custom REPL")

            # Ensure config consistency
            if not hasattr(self.repl, "config"):
                self.repl.config = self.config

            # Sync bash permissions
            if hasattr(self.repl.config, "permissions") and hasattr(
                self.repl.config.permissions, "bash"
            ):
                self.repl.config.permissions.bash.enabled = True
            elif hasattr(self.repl.config, "enable_bash"):
                self.repl.config.enable_bash = True

            self._auto_connect_mcp = auto_connect_mcp and hasattr(self.repl, "mcp_manager")
            # When using custom REPL, we don't know if session was resumed
            # Default to False (show welcome panel)
            self._is_resumed_session = False
        else:
            self.config_manager = config_manager or ConfigManager(self.working_dir)
            self.config = self.config_manager.load_config()
            self.config_manager.ensure_directories()

            import os

            env_session_dir = os.environ.get("SWECLI_SESSION_DIR")
            if session_manager is not None:
                self.session_manager = session_manager
            elif env_session_dir:
                self.session_manager = SessionManager(session_dir=Path(env_session_dir))
            else:
                self.session_manager = SessionManager(working_dir=self.working_dir)

            # Handle session resumption
            session_loaded = False
            if resume_session_id:
                # Resume specific session by ID
                try:
                    self.session_manager.load_session(resume_session_id)
                    session_loaded = True
                except FileNotFoundError:
                    # Session not found - will fall back to creating new session
                    from rich.console import Console

                    Console().print(
                        f"[yellow]Session '{resume_session_id}' not found. Starting new session.[/yellow]"
                    )
            elif continue_session:
                # Resume most recent session for this working directory
                session = self.session_manager.load_latest_session(self.working_dir)
                if session:
                    session_loaded = True
                else:
                    from rich.console import Console

                    Console().print(
                        "[yellow]No previous session found for this directory. Starting new session.[/yellow]"
                    )

            if not session_loaded:
                self.session_manager.create_session(working_directory=str(self.working_dir))

            # Store whether we resumed an existing session (for UI decisions)
            self._is_resumed_session = session_loaded

            self.repl = REPL(self.config_manager, self.session_manager, is_tui=True)
            self.repl.mode_manager.set_mode(OperationMode.NORMAL)
            self.repl.approval_manager = ChatApprovalManager(self.repl.console)
            if self._dangerously_skip_permissions:
                self.repl.approval_manager.set_autonomy_level("Auto")

            if hasattr(self.repl.config, "permissions") and hasattr(
                self.repl.config.permissions, "bash"
            ):
                self.repl.config.permissions.bash.enabled = True
            elif hasattr(self.repl.config, "enable_bash"):
                self.repl.config.enable_bash = True

            self._auto_connect_mcp = auto_connect_mcp and hasattr(self.repl, "mcp_manager")

    def _init_debug_logger(self) -> None:
        """Initialize the per-session debug logger when verbose mode is active."""
        from swecli.core.debug import SessionDebugLogger, set_debug_logger

        if not getattr(self.config, "verbose", False):
            set_debug_logger(None)
            return

        session = self.session_manager.get_current_session()
        if not session:
            set_debug_logger(None)
            return

        logger = SessionDebugLogger(self.session_manager.session_dir, session.id)
        set_debug_logger(logger)
        logger.log(
            "session_start",
            "runner",
            session_id=session.id,
            working_dir=str(self.working_dir),
            model=getattr(self.config, "model", "unknown"),
            provider=getattr(self.config, "model_provider", "unknown"),
        )

    def _setup_components(self, auto_connect_mcp: bool) -> None:
        """Initialize helper components (History, DOM, MCP, etc)."""
        self._history_hydrator = HistoryHydrator(
            session_manager=self.session_manager,
            working_dir=self.working_dir,
        )
        self._tool_renderer = ToolRenderer(self.working_dir)
        self._history_hydrator.set_tool_renderer(self._tool_renderer)
        self._history_hydrator.snapshot_history()

        self.model_config_manager = ModelConfigManager(self.config_manager, self.repl)
        self.console_bridge = ConsoleBridge(self.repl.console)
        self.console_bridge.install()

        self.mcp_controller = MCPController(
            self.repl,
            callbacks={
                "enqueue_console_text": self.console_bridge.enqueue_text,
                "refresh_ui_config": self.model_config_manager.refresh_ui_config,
            },
        )
        self.mcp_controller.set_auto_connect(auto_connect_mcp)

        self.command_router = CommandRouter(
            self.repl,
            self.working_dir,
            callbacks={
                "enqueue_console_text": self.console_bridge.enqueue_text,
                "start_mcp_connect_thread": self.mcp_controller.start_autoconnect_thread,
                "refresh_ui_config": self.model_config_manager.refresh_ui_config,
            },
        )

        self.message_processor = MessageProcessor(
            app=None,  # Set in on_ready
            callbacks={
                "handle_command": self._run_command,
                "handle_query": self._run_query,
                "render_responses": self._render_responses,
                "on_error": lambda msg: self.app.notify_processing_error(msg),
                "on_command_error": lambda msg: (
                    self.app.conversation.add_error(msg)
                    if hasattr(self.app, "conversation")
                    else None
                ),
            },
        )

    def _setup_app(self) -> None:
        """Initialize the Textual application instance."""
        # Get model display name and slot summaries from config
        # Use snapshot for consistent provider name formatting (e.g., "OpenAI" not "openai")
        snapshot = self.model_config_manager.get_model_config_snapshot()
        normal_info = snapshot.get("normal", {})
        provider_display = normal_info.get("provider_display", self.config.model_provider)
        model_name = normal_info.get("model_display", self.config.model)
        model_display = f"{provider_display}/{model_name}" if provider_display else model_name
        model_slots = self.model_config_manager._build_model_slots(snapshot)

        create_kwargs = {
            "on_message": self.enqueue_message,
            "model": model_display,
            "model_slots": model_slots,
            "on_cycle_mode": self._cycle_mode,
            "completer": getattr(self.repl, "completer", None),
            "on_model_selected": self.model_config_manager.apply_model_selection,
            "get_model_config": self.model_config_manager.get_model_config_snapshot,
            "on_interrupt": self._handle_interrupt,
            "working_dir": str(self.working_dir),
            "todo_handler": (
                getattr(self.repl.tool_registry, "todo_handler", None)
                if hasattr(self.repl, "tool_registry")
                else None
            ),
            "is_resumed_session": self._is_resumed_session,
        }

        if self._auto_connect_mcp:
            downstream_on_ready = lambda: self.mcp_controller.start_autoconnect_thread(self._loop)
        else:
            downstream_on_ready = self.mcp_controller.notify_manual_connect

        # Create on_ready callback that hydrates history then calls downstream
        def _on_ready_with_hydration() -> None:
            self.model_config_manager.set_app(self.app)
            self.command_router.set_app(self.app)
            self.message_processor.set_app(self.app)
            self.console_bridge.set_app(self.app)
            self.mcp_controller.set_app(self.app)
            # Wire up agent creator with config manager for path resolution
            if hasattr(self.app, "_agent_creator"):
                self.app._agent_creator.set_config_manager(self.config_manager)
            # Wire up skill creator with config manager for path resolution
            if hasattr(self.app, "_skill_creator"):
                self.app._skill_creator.set_config_manager(self.config_manager)
            self._history_hydrator.start_async_hydration(self.app)
            # Sync status bar to Auto if --dangerously-skip-permissions (after mount)
            if self._dangerously_skip_permissions and hasattr(self.app, "status_bar"):
                self.app.status_bar.set_autonomy("Auto")
            if downstream_on_ready:
                downstream_on_ready()
            # Post initial message as a Submitted event so it flows through
            # the normal UI submit path (welcome panel dismissal, MessageController, etc.)
            if self._initial_message:
                from swecli.ui_textual.widgets.chat_text_area import ChatTextArea

                self.app.input_field.post_message(
                    ChatTextArea.Submitted(self.app.input_field, self._initial_message)
                )

        create_kwargs["on_ready"] = _on_ready_with_hydration

        try:
            self.app = create_chat_app(**create_kwargs)
        except TypeError:
            legacy_kwargs = {
                "on_message": self.enqueue_message,
                "model": model_display,
                "model_slots": model_slots,
                "on_cycle_mode": self._cycle_mode,
                "completer": getattr(self.repl, "completer", None),
            }
            self.app = create_chat_app(**legacy_kwargs)

        if hasattr(self.repl.approval_manager, "chat_app"):
            self.repl.approval_manager.chat_app = self.app

        # Store approval manager reference on the app for action_cycle_autonomy
        self.app._approval_manager = self.repl.approval_manager

        # Lock autonomy if --dangerously-skip-permissions was used
        # (status bar sync happens in _on_ready_with_hydration, after mount)
        if self._dangerously_skip_permissions:
            self.app._autonomy_locked = True

        # Store thinking handler reference for action_toggle_thinking to sync with query_processor
        self.app._thinking_handler = getattr(self.repl.tool_registry, "thinking_handler", None)

        # Wire up ask_user_tool callback to UI controller
        if hasattr(self.repl, "ask_user_tool") and self.repl.ask_user_tool:
            ask_user_tool = self.repl.ask_user_tool

            def _ask_user_ui_callback(questions):
                """Bridge sync callback to async UI controller.

                Called from background thread, schedules async controller on main loop.
                """
                future = asyncio.run_coroutine_threadsafe(
                    self.app._ask_user_controller.start(questions),
                    self._loop,
                )
                # Block calling thread until user responds
                return future.result()

            ask_user_tool.set_prompt_callback(_ask_user_ui_callback)

        if hasattr(self.repl, "config_commands"):
            self.repl.config_commands.chat_app = self.app

        # Store runner reference on app for queue indicator updates
        self.app._runner = self

        # Link console bridge to app for rendering
        self.console_bridge.set_app(self.app)

    def get_queue_size(self) -> int:
        """Get number of messages waiting in queue."""
        if hasattr(self, "message_processor"):
            return self.message_processor.get_queue_size()
        return 0

    def pause_processing(self) -> None:
        """Pause message processing."""
        if hasattr(self, "message_processor"):
            self.message_processor.pause()

    def resume_processing(self) -> None:
        """Resume message processing."""
        if hasattr(self, "message_processor"):
            self.message_processor.resume()

    def enqueue_message(self, text: str, needs_display: bool = False) -> None:
        """Queue a message from the UI for processing.

        Args:
            text: The message text to queue
            needs_display: If True, the message will be displayed in conversation
                          when it starts processing (because it was queued while
                          another message was being processed)
        """
        if hasattr(self, "message_processor"):
            self.message_processor.enqueue_message(text, needs_display)

    def _run_query(self, message: str) -> list[ChatMessage]:
        """Execute a user query via the REPL and return new session messages."""
        import traceback
        from swecli.core.debug import get_debug_logger

        get_debug_logger().log(
            "message_submitted", "runner", text=message[:200], source="user"
        )

        # Check for plan approval in PLAN mode
        if self._check_and_execute_plan_approval(message):
            # Plan approval handled, return updated messages
            session = self.session_manager.get_current_session()
            return list(session.messages) if session else []

        try:
            config = self.config_manager.get_config()
            self.config = config
            model_info = config.get_model_info()
        except Exception as exc:  # pragma: no cover - defensive guard
            self.app.notify_processing_error(
                f"Send failed: unable to validate active model ({exc})."
            )
            return []

        if model_info is None:
            self.app.notify_processing_error(
                "Send failed: configured Normal model is missing. Run /models to choose a valid model."
            )
            return []

        # Validate API key before attempting to chat
        try:
            config.get_api_key()
        except ValueError as e:
            self.app.notify_processing_error(f"Send failed: {e}")
            return []

        session = self.session_manager.get_current_session()
        previous_count = len(session.messages) if session else 0

        try:
            # Create UI callback for real-time tool display
            conversation_widget = None
            try:
                # Use the same query method the app uses to get the conversation widget
                from swecli.ui_textual.chat_app import ConversationLog

                conversation_widget = self.app.query_one("#conversation", ConversationLog)
            except Exception:
                # Fallback to direct attribute access
                if hasattr(self.app, "conversation") and self.app.conversation is not None:
                    conversation_widget = self.app.conversation

            if conversation_widget is not None:
                # Apply debug_logging setting from config
                config = self.config_manager.get_config()
                conversation_widget.set_debug_enabled(config.debug_logging)

                from swecli.ui_textual.ui_callback import TextualUICallback

                ui_callback = TextualUICallback(conversation_widget, self.app, self.working_dir)
            else:
                # Create a mock callback for when app is not mounted (e.g., during testing)
                # BaseUICallback provides no-op implementations for all methods
                from swecli.ui_textual.callback_interface import BaseUICallback

                ui_callback = BaseUICallback()

            # Temporarily disable console bridge to prevent duplicate rendering
            # All relevant messages are already in session.messages
            self.console_bridge.uninstall()

            try:
                # Process query with UI callback for real-time display
                if hasattr(self.repl, "_process_query_with_callback"):
                    self.repl._process_query_with_callback(message, ui_callback)
                else:
                    # Fallback to normal processing if callback method doesn't exist
                    self.repl._process_query(message)
            finally:
                # Restore bridge
                self.console_bridge.install()

            session = self.session_manager.get_current_session()
            if not session:
                return []

            new_messages = session.messages[previous_count:]

            # After PLAN mode query, check if response contains a plan to store
            if self.repl.mode_manager.current_mode == OperationMode.PLAN:
                self._store_plan_from_response(new_messages)

            return new_messages
        except Exception as e:
            error_msg = f"[ERROR] Query processing failed: {str(e)}\n{traceback.format_exc()}"
            self.console_bridge.enqueue_text(error_msg)
            return []

    def _check_and_execute_plan_approval(self, message: str) -> bool:
        """Check if user is approving a pending plan and execute it.

        Args:
            message: User message to check

        Returns:
            True if plan approval was handled, False otherwise
        """
        # Only check if we're in PLAN mode with a pending plan
        if self.repl.mode_manager.current_mode != OperationMode.PLAN:
            return False

        if not self.repl.mode_manager.has_pending_plan():
            return False

        # Check if message is an approval phrase
        normalized = message.strip().lower()
        if normalized not in PLAN_APPROVAL_PHRASES:
            # Not an approval - clear the pending plan and continue normally
            self.repl.mode_manager.clear_plan()
            return False

        # Get the pending plan
        plan_text, plan_steps, plan_goal = self.repl.mode_manager.get_pending_plan()
        if not plan_text or not plan_steps:
            return False

        # Switch to NORMAL mode (callback handles agent swapping)
        self.repl.mode_manager.set_mode(OperationMode.NORMAL)

        # Update UI to show mode change
        if hasattr(self.app, "status_bar"):
            self.app.status_bar.set_mode("normal")

        # Create todos from plan steps
        todo_handler = getattr(self.repl.tool_registry, "todo_handler", None)
        if todo_handler:
            from swecli.core.agents.components import extract_plan_from_response

            parsed = extract_plan_from_response(f"---BEGIN PLAN---\n{plan_text}\n---END PLAN---")
            if parsed:
                todos = parsed.get_todo_items()
                todo_handler.write_todos(todos)

        # Clear the pending plan
        self.repl.mode_manager.clear_plan()

        # Execute the plan by sending it to the normal agent
        execution_prompt = f"""Execute this approved implementation plan step by step:

{plan_text}

Work through each implementation step in order. Mark each todo item as 'in_progress' when starting and 'completed' when done.
"""
        # Process the execution prompt through normal agent
        self.repl._process_query(execution_prompt)

        return True

    def _store_plan_from_response(self, messages: list[ChatMessage]) -> None:
        """Extract and store plan from assistant response for later approval.

        Args:
            messages: New messages from the response
        """
        # Look for assistant messages with plan content
        for msg in messages:
            if msg.role != Role.ASSISTANT:
                continue

            content = msg.content or ""
            if "---BEGIN PLAN---" not in content:
                continue

            # Try to parse the plan
            parsed = extract_plan_from_response(content)
            if parsed and parsed.is_valid():
                # Store the plan for approval
                self.repl.mode_manager.store_plan(
                    plan_text=parsed.raw_text,
                    steps=parsed.steps,
                    goal=parsed.goal,
                )
                break

    def _run_command(self, command: str) -> None:
        """Execute a slash command and capture console output."""
        if self.command_router.route_command(command):
            return
        self.command_router.run_generic_command(command)

    def _handle_interrupt(self) -> bool:
        """Handle interrupt request from UI (ESC key press).

        Returns:
            True if interrupt was requested, False if no task is running
        """
        from swecli.ui_textual.debug_logger import debug_log
        debug_log("Runner", "_handle_interrupt called")
        has_qp = hasattr(self.repl, "query_processor") and self.repl.query_processor
        debug_log("Runner", f"has query_processor={has_qp}")

        if has_qp:
            result = self.repl.query_processor.request_interrupt()
            debug_log("Runner", f"query_processor.request_interrupt() returned: {result}")
            return result
        return False

    def _cycle_mode(self) -> str:
        """Toggle between NORMAL and PLAN modes and return the active mode.

        Note:
            The mode_manager callback handles agent swapping automatically.
        """
        current = self.repl.mode_manager.current_mode
        from swecli.core.runtime import OperationMode

        new_mode = OperationMode.PLAN if current == OperationMode.NORMAL else OperationMode.NORMAL
        # set_mode triggers the callback which handles agent swapping
        self.repl.mode_manager.set_mode(new_mode)

        return new_mode.value

    def _render_responses(self, messages: list[ChatMessage]) -> None:
        """Render new session messages inside the Textual conversation log."""

        buffer_started = False
        assistant_text_rendered = False

        for msg in messages:
            if msg.role == Role.ASSISTANT:
                if hasattr(self.app, "_stop_local_spinner"):
                    self.app._stop_local_spinner()

                if hasattr(self.app, "start_console_buffer"):
                    self.app.start_console_buffer()
                    buffer_started = True

                content = msg.content.strip()
                if hasattr(self.app, "_normalize_paragraph"):
                    normalized = self.app._normalize_paragraph(content)
                    if normalized:
                        self.app._pending_assistant_normalized = normalized
                        self.console_bridge.set_last_assistant_message(normalized)
                else:
                    self.console_bridge.set_last_assistant_message(content if content else None)

                # Only render assistant messages that DON'T have tool calls
                # Messages with tool calls were already displayed in real-time by callbacks
                # Note: Simple text messages may also have been displayed via on_assistant_message
                # callback - add_assistant_message has deduplication to prevent double-render
                has_tool_calls = getattr(msg, "tool_calls", None) and len(msg.tool_calls) > 0

                if content and not has_tool_calls:
                    self.app.conversation.add_assistant_message(msg.content)
                    # Force refresh to ensure immediate visual update
                    if hasattr(self.app.conversation, "refresh"):
                        self.app.conversation.refresh()
                    if hasattr(self.app, "record_assistant_message"):
                        self.app.record_assistant_message(msg.content)

                    self.console_bridge.set_last_assistant_message(content)
                    self.console_bridge.set_suppress_duplicate(True)
                    assistant_text_rendered = True

                # Skip rendering messages with tool calls - already shown in real-time
            elif msg.role == Role.SYSTEM:
                self.app.conversation.add_system_message(msg.content)
            # Skip USER messages - they're already displayed by the UI when user types them

        if buffer_started and hasattr(self.app, "stop_console_buffer"):
            self.app.stop_console_buffer()

    def run(self) -> None:
        """Launch the Textual application and background consumer."""

        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_app())
        finally:
            # Log session end before cleanup
            from swecli.core.debug import get_debug_logger, set_debug_logger

            get_debug_logger().log("session_end", "runner")
            set_debug_logger(None)

            _reset_terminal_mouse_mode()  # Ensure mouse mode is disabled
            self.repl._cleanup()
            with contextlib.suppress(RuntimeError):
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            asyncio.set_event_loop(None)
            self._loop.close()

    async def _run_app(self) -> None:
        """Run Textual app alongside background processing tasks."""

        # Start message processor thread (uses queue.Queue, not asyncio)
        self.message_processor.start()
        # Start console bridge task (uses asyncio queue)
        self.console_bridge.start(self._loop)
        try:
            # Use alternate screen mode (inline=False) for clean TUI with no terminal noise
            # Enable mouse for scroll support; text selection requires Option/Alt + drag
            await self.app.run_async(inline=False, mouse=False)
        finally:
            # Stop message processor thread
            self.message_processor.stop()
            # Stop console bridge task
            self.console_bridge.stop()

    def _on_app_mounted(self) -> None:
        """Called when the Textual app is fully mounted and ready."""
        # Schedule MCP auto-connect if enabled
        self.mcp_controller.start_autoconnect_thread(self._loop)

        # If auto-connect isn't enabled, show tip
        if not self.mcp_controller._auto_connect_enabled:
            self.mcp_controller.notify_manual_connect()


def launch_textual_cli(
    message=None,
    continue_session: bool = False,
    resume_session_id: Optional[str] = None,
    dangerously_skip_permissions: bool = False,
    **kwargs,
) -> None:
    """Public helper for launching the Textual UI from external callers.

    Args:
        message: Optional message to process automatically
        continue_session: If True, resume the most recent session for the working directory
        resume_session_id: Specific session ID to resume
        dangerously_skip_permissions: If True, set autonomy to Auto from startup
        **kwargs: Additional arguments passed to TextualRunner
    """

    if "auto_connect_mcp" not in kwargs:
        auto_env = os.getenv("SWECLI_MCP_AUTOCONNECT", "").strip().lower()
        if auto_env in {"1", "true", "yes", "on"}:
            kwargs["auto_connect_mcp"] = True

    runner = TextualRunner(
        continue_session=continue_session,
        resume_session_id=resume_session_id,
        initial_message=message,
        dangerously_skip_permissions=dangerously_skip_permissions,
        **kwargs,
    )

    runner.run()


if __name__ == "__main__":
    launch_textual_cli()
