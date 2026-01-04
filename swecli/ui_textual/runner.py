"""Entry point helper for launching the Textual chat UI alongside core SWE-CLI services."""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import os
import queue
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Optional


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

from rich.ansi import AnsiDecoder
from rich.text import Text

from swecli.core.agents.components import extract_plan_from_response
from swecli.core.runtime import ConfigManager, OperationMode
from swecli.core.context_engineering.history import SessionManager
from swecli.models.message import ChatMessage, Role
from swecli.repl.repl import REPL
from swecli.ui_textual.managers.approval_manager import ChatApprovalManager
from swecli.ui_textual.chat_app import create_chat_app
from swecli.ui_textual.constants import TOOL_ERROR_SENTINEL
from swecli.ui_textual.utils import build_tool_call_text

# Approval phrases for plan execution
PLAN_APPROVAL_PHRASES = {
    "yes", "approve", "execute", "go ahead", "do it", "proceed",
    "start", "run", "ok", "okay", "y", "sure", "go",
}


class TextualRunner:
    """Orchestrates the Textual chat UI with the core SWE-CLI runtime."""

    def __init__(
        self,
        *,
        working_dir: Optional[Path] = None,
        resume_session: Optional[str] = None,
        continue_session: bool = False,
        repl: Optional[REPL] = None,
        config_manager: Optional[ConfigManager] = None,
        session_manager: Optional[SessionManager] = None,
        auto_connect_mcp: bool = False,
    ) -> None:
        self.working_dir = Path(working_dir or Path.cwd()).resolve()
        self._initial_messages: list[ChatMessage] = []
        self._history_restored = False

        if repl is not None:
            self.repl = repl
            self.config_manager = config_manager or getattr(repl, "config_manager", ConfigManager(self.working_dir))
            self.config = getattr(repl, "config", None) or self.config_manager.get_config()
            self.session_manager = session_manager or getattr(repl, "session_manager", None)
            if self.session_manager is None:
                raise ValueError("SessionManager is required when providing a custom REPL")
            if not hasattr(self.repl, "config"):
                self.repl.config = self.config
            if hasattr(self.repl.config, "permissions") and hasattr(self.repl.config.permissions, "bash"):
                self.repl.config.permissions.bash.enabled = True
            elif hasattr(self.repl.config, "enable_bash"):
                self.repl.config.enable_bash = True
            self._auto_connect_mcp = auto_connect_mcp and hasattr(self.repl, "mcp_manager")
        else:
            self.config_manager = config_manager or ConfigManager(self.working_dir)
            self.config = self.config_manager.load_config()
            self.config_manager.ensure_directories()

            session_root = Path(self.config.session_dir).expanduser()
            self.session_manager = session_manager or SessionManager(session_root)
            self._configure_session(resume_session, continue_session)

            self.repl = REPL(self.config_manager, self.session_manager)
            self.repl.mode_manager.set_mode(OperationMode.NORMAL)
            self.repl.approval_manager = ChatApprovalManager(self.repl.console)
            if hasattr(self.repl.config, "permissions") and hasattr(self.repl.config.permissions, "bash"):
                self.repl.config.permissions.bash.enabled = True
            elif hasattr(self.repl.config, "enable_bash"):
                self.repl.config.enable_bash = True
            self._auto_connect_mcp = auto_connect_mcp and hasattr(self.repl, "mcp_manager")

        self._initial_messages = self._snapshot_session_history()

        # Get model display name and slot summaries from config
        model_display = f"{self.config.model_provider}/{self.config.model}"
        model_slots = self._build_model_slots()

        create_kwargs = {
            "on_message": self.enqueue_message,
            "model": model_display,
            "model_slots": model_slots,
            "on_cycle_mode": self._cycle_mode,
            "completer": getattr(self.repl, "completer", None),
            "on_model_selected": self._apply_model_selection,
            "get_model_config": self._get_model_config_snapshot,
            "on_interrupt": self._handle_interrupt,
            "working_dir": str(self.working_dir),
            "todo_handler": getattr(self.repl.tool_registry, "todo_handler", None) if hasattr(self.repl, "tool_registry") else None,
        }
        if self._auto_connect_mcp:
            create_kwargs["on_ready"] = self._start_mcp_connect_thread
        else:
            create_kwargs["on_ready"] = self._notify_manual_mcp_connect
        create_kwargs["on_ready"] = self._wrap_on_ready_callback(create_kwargs.get("on_ready"))

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
        if hasattr(self.repl, "config_commands"):
            self.repl.config_commands.chat_app = self.app

        # Store runner reference on app for queue indicator updates
        self.app._runner = self

        # Queue holds tuples of (message, needs_display)
        # needs_display=True means the message wasn't shown yet (was queued while processing)
        # Using queue.Queue (thread-safe) instead of asyncio.Queue for cross-thread access
        self._pending: queue.Queue[tuple[str, bool]] = queue.Queue()
        self._processor_thread: threading.Thread | None = None
        self._processor_stop = threading.Event()
        self._console_queue: asyncio.Queue[str] = asyncio.Queue()
        self._ansi_decoder = AnsiDecoder()
        self._install_console_bridge()
        self._loop = asyncio.new_event_loop()
        self._console_task: asyncio.Task[None] | None = None
        self._connect_inflight = False
        self._last_console_line: str | None = None
        self._last_assistant_message: str | None = None
        self._suppress_console_duplicate = False
        self._last_assistant_message_normalized: str | None = None

        # Set up queue indicator callback
        self._queue_update_callback: Callable[[int], None] | None = self.app.update_queue_indicator

    def _snapshot_session_history(self) -> list[ChatMessage]:
        """Capture a copy of existing session messages for later hydration."""
        manager = getattr(self, "session_manager", None)
        if manager is None:
            return []
        session = manager.get_current_session()
        if session is None or not session.messages:
            return []
        return [message.model_copy(deep=True) for message in session.messages]

    def _wrap_on_ready_callback(
        self,
        downstream: Optional[Callable[[], None]],
    ) -> Callable[[], None]:
        """Ensure history hydration runs before any existing on_ready hook."""

        def _callback() -> None:
            # Start async history hydration in background - don't block UI
            self._start_async_history_hydration()
            if downstream:
                downstream()

        return _callback

    def _start_async_history_hydration(self) -> None:
        """Start hydrating conversation history in background batches."""
        if self._history_restored or not self._initial_messages:
            self._history_restored = True
            return

        # Run hydration in a worker to not block the UI thread
        import threading

        def hydrate_in_batches():
            conversation = getattr(self.app, "conversation", None)
            if conversation is None:
                self._history_restored = True
                return

            # Clear and prepare - do this on UI thread
            self.app.call_from_thread(conversation.clear)

            history = getattr(self.app, "_history", None)
            record_assistant = getattr(self.app, "record_assistant_message", None)

            # Process messages in batches to keep UI responsive
            BATCH_SIZE = 5
            messages = self._initial_messages

            for i in range(0, len(messages), BATCH_SIZE):
                batch = messages[i:i + BATCH_SIZE]

                # Process batch on UI thread
                def process_batch(batch_messages=batch):
                    for message in batch_messages:
                        content = (message.content or "").strip()
                        if message.role == Role.USER:
                            if not content:
                                continue
                            conversation.add_user_message(content)
                            if history is not None and hasattr(history, "record"):
                                history.record(content)
                        elif message.role == Role.ASSISTANT:
                            if content:
                                conversation.add_assistant_message(content)
                                if callable(record_assistant):
                                    record_assistant(content)
                            if getattr(message, "tool_calls", None):
                                self._render_stored_tool_calls(conversation, message.tool_calls)
                            elif not content:
                                continue
                        elif message.role == Role.SYSTEM:
                            if not content:
                                continue
                            conversation.add_system_message(content)

                self.app.call_from_thread(process_batch)

                # Small delay between batches to let UI breathe
                import time
                time.sleep(0.01)

            self._history_restored = True

        thread = threading.Thread(target=hydrate_in_batches, daemon=True)
        thread.start()

    def _build_model_slots(self) -> dict[str, tuple[str, str]]:
        """Prepare formatted model slot information for the footer."""

        def format_model(
            provider: Optional[str],
            model_id: Optional[str],
        ) -> tuple[str, str] | None:
            if not model_id:
                return None
            provider_display = provider.capitalize() if provider else "Unknown"
            return provider_display, model_id

        config = self.config
        slots: dict[str, tuple[str, str]] = {}

        normal = format_model(config.model_provider, config.model)
        if normal:
            slots["normal"] = normal

        if config.model_thinking and config.model_thinking != config.model:
            thinking = format_model(
                config.model_thinking_provider,
                config.model_thinking,
            )
            if thinking:
                slots["thinking"] = thinking

        if config.model_vlm and config.model_vlm != config.model:
            vision = format_model(
                config.model_vlm_provider,
                config.model_vlm,
            )
            if vision:
                slots["vision"] = vision

        return slots

    def _refresh_ui_config(self) -> None:
        """Refresh cached config-driven UI indicators after config changes."""
        # Refresh cached config instance (commands may mutate or reload it)
        self.config = self.config_manager.get_config()
        model_display = f"{self.config.model_provider}/{self.config.model}"
        if hasattr(self.app, "update_primary_model"):
            self.app.update_primary_model(model_display)
        if hasattr(self.app, "update_model_slots"):
            self.app.update_model_slots(self._build_model_slots())

    def _hydrate_conversation_history(self) -> None:
        """Replay the persisted session transcript into the Textual conversation log."""

        if self._history_restored:
            return

        if not self._initial_messages:
            self._history_restored = True
            return

        conversation = getattr(self.app, "conversation", None)
        if conversation is None:
            return

        conversation.clear()
        history = getattr(self.app, "_history", None)
        record_assistant = getattr(self.app, "record_assistant_message", None)

        for message in self._initial_messages:
            content = (message.content or "").strip()
            if message.role == Role.USER:
                if not content:
                    continue
                conversation.add_user_message(content)
                if history is not None and hasattr(history, "record"):
                    history.record(content)
            elif message.role == Role.ASSISTANT:
                if content:
                    conversation.add_assistant_message(content)
                    if callable(record_assistant):
                        record_assistant(content)
                if getattr(message, "tool_calls", None):
                    self._render_stored_tool_calls(conversation, message.tool_calls)
                elif not content:
                    continue
            elif message.role == Role.SYSTEM:
                if not content:
                    continue
                conversation.add_system_message(content)

        self._history_restored = True

    def _render_stored_tool_calls(self, conversation, tool_calls: list[Any]) -> None:
        """Replay historical tool calls using same logic as live display."""
        if not tool_calls:
            return

        from swecli.ui_textual.formatters.style_formatter import StyleFormatter
        formatter = StyleFormatter()

        for tool_call in tool_calls:
            tool_name = getattr(tool_call, "name", "tool")
            try:
                parameters = self._coerce_tool_parameters(getattr(tool_call, "parameters", {}))
            except Exception:
                parameters = {}
            result = getattr(tool_call, "result", None)

            # Resolve paths for display (same as ui_callback._resolve_paths_in_args)
            display_params = self._resolve_paths_for_display(parameters)

            # Display tool call header (same as on_tool_call)
            display = build_tool_call_text(tool_name, display_params)
            conversation.add_tool_call(display)
            if hasattr(conversation, "stop_tool_execution"):
                conversation.stop_tool_execution()

            # Handle result using same logic as on_tool_result() in ui_callback.py
            if isinstance(result, str):
                result = {"success": True, "output": result}

            # Skip interrupted operations (same as live display - ui_callback.py line 402)
            if isinstance(result, dict) and result.get("interrupted"):
                continue

            # Handle spawn_subagent with nested tool calls
            if tool_name == "spawn_subagent":
                nested = getattr(tool_call, "nested_tool_calls", [])
                if nested:
                    self._render_nested_tool_calls(conversation, nested, formatter)
                continue

            # Bash commands: use add_bash_output_box (mirrors on_tool_result)
            if tool_name in ("bash_execute", "run_command", "Bash") and isinstance(result, dict):
                is_error = not result.get("success", True)
                command = parameters.get("command", "")
                working_dir = str(self.working_dir)

                output_parts = []
                if result.get("stdout"):
                    output_parts.append(result["stdout"])
                if result.get("stderr"):
                    output_parts.append(result["stderr"])
                combined_output = "\n".join(output_parts).strip()
                if not combined_output and result.get("output"):
                    output_value = result["output"].strip()
                    if output_value not in ("Command executed", "Command execution failed"):
                        combined_output = output_value

                if hasattr(conversation, "add_bash_output_box"):
                    conversation.add_bash_output_box(combined_output, is_error, command, working_dir, 0)
                continue

            # edit_file: Use add_edit_diff_result for colored diff (mirrors ui_callback.py lines 516-533)
            if tool_name == "edit_file" and isinstance(result, dict) and result.get("success"):
                diff_text = result.get("diff", "")
                if diff_text and hasattr(conversation, 'add_edit_diff_result'):
                    file_path = parameters.get("file_path", "unknown")
                    lines_added = result.get("lines_added", 0) or 0
                    lines_removed = result.get("lines_removed", 0) or 0
                    summary = f"Updated {file_path} with {lines_added} addition(s) and {lines_removed} removal(s)"
                    conversation.add_tool_result(summary)
                    conversation.add_edit_diff_result(diff_text, depth=0)
                    continue

            # Todo tools: Use add_todo_sub_results with symbols (mirrors ui_callback.py)
            if tool_name == "write_todos" and isinstance(result, dict) and result.get("success"):
                todos = parameters.get("todos", [])
                if todos and hasattr(conversation, 'add_todo_sub_results'):
                    items = []
                    for todo in todos:
                        status = todo.get("status", "pending")
                        content = todo.get("content", "")
                        symbol = "○" if status == "pending" else ("▶" if status == "in_progress" else "✓")
                        items.append((symbol, content))
                    conversation.add_todo_sub_results(items, depth=0)
                    continue

            # Other tools: use StyleFormatter (mirrors on_tool_result)
            if isinstance(result, dict):
                formatted = formatter.format_tool_result(tool_name, parameters, result)
                lines = []
                if isinstance(formatted, str):
                    for line in formatted.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("⎿"):
                            result_text = stripped.lstrip("⎿").strip()
                            if result_text:
                                lines.append(result_text)
                if lines:
                    conversation.add_tool_result("\n".join(lines))
            else:
                # Fallback for non-dict results
                fallback_lines = self._format_tool_history_lines(tool_call)
                if fallback_lines:
                    conversation.add_tool_result("\n".join(fallback_lines))

    def _render_nested_tool_calls(self, conversation, nested_calls: list[Any], formatter: Any) -> None:
        """Render nested tool calls using existing conversation log methods."""
        for nested in nested_calls:
            tool_name = getattr(nested, "name", "tool")
            parameters = self._coerce_tool_parameters(getattr(nested, "parameters", {}))
            result = getattr(nested, "result", None)
            depth = 1

            # Convert string result to dict
            if isinstance(result, str):
                result = {"success": True, "output": result}

            # Skip interrupted operations
            if isinstance(result, dict) and result.get("interrupted"):
                continue

            # Resolve paths for display (same as ui_callback._resolve_paths_in_args)
            display_params = self._resolve_paths_for_display(parameters)

            # Display nested tool call header
            display = build_tool_call_text(tool_name, display_params)
            if hasattr(conversation, "add_nested_tool_call"):
                conversation.add_nested_tool_call(display, depth, "subagent")

            # Display result FIRST, then complete
            success = result.get("success", True) if isinstance(result, dict) else True

            if tool_name in ("bash_execute", "run_command", "Bash") and isinstance(result, dict):
                # Bash output box
                is_error = not result.get("success", True)
                command = parameters.get("command", "")
                working_dir = parameters.get("working_dir", str(self.working_dir))
                output = result.get("stdout", "") or result.get("output", "")
                if result.get("stderr"):
                    output = (output + "\n" + result["stderr"]).strip() if output else result["stderr"]
                if hasattr(conversation, "add_bash_output_box"):
                    conversation.add_bash_output_box(output.strip(), is_error, command, working_dir, depth)
            elif tool_name == "edit_file" and isinstance(result, dict) and result.get("success"):
                # Colored diff display
                diff_text = result.get("diff", "")
                if diff_text and hasattr(conversation, 'add_edit_diff_result'):
                    file_path = parameters.get("file_path", "unknown")
                    lines_added = result.get("lines_added", 0) or 0
                    lines_removed = result.get("lines_removed", 0) or 0
                    summary = f"Updated {file_path} with {lines_added} addition(s) and {lines_removed} removal(s)"
                    if hasattr(conversation, "add_nested_tool_sub_results"):
                        conversation.add_nested_tool_sub_results([summary], depth)
                    conversation.add_edit_diff_result(diff_text, depth)
            elif tool_name == "write_todos" and isinstance(result, dict) and result.get("success"):
                # Todo symbols
                todos = parameters.get("todos", [])
                if todos and hasattr(conversation, 'add_todo_sub_results'):
                    items = []
                    for todo in todos:
                        status = todo.get("status", "pending")
                        content = todo.get("content", "")
                        symbol = "○" if status == "pending" else ("▶" if status == "in_progress" else "✓")
                        items.append((symbol, content))
                    conversation.add_todo_sub_results(items, depth)
            elif isinstance(result, dict):
                # Generic StyleFormatter
                formatted = formatter.format_tool_result(tool_name, parameters, result)
                lines = [ln.lstrip("⎿").strip() for ln in formatted.splitlines() if ln.strip().startswith("⎿")]
                if lines and hasattr(conversation, "add_nested_tool_sub_results"):
                    conversation.add_nested_tool_sub_results(lines, depth)

            # Complete AFTER result display
            if hasattr(conversation, "complete_nested_tool_call"):
                conversation.complete_nested_tool_call(tool_name, depth, "subagent", success)

    @staticmethod
    def _coerce_tool_parameters(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        return {}

    def _resolve_paths_for_display(self, params: dict) -> dict:
        """Resolve relative paths to absolute for display (same as ui_callback._resolve_paths_in_args)."""
        PATH_KEYS = {"path", "file_path", "working_dir", "directory", "dir", "target"}
        result = dict(params)
        for key in PATH_KEYS:
            if key in result and isinstance(result[key], str):
                path = result[key]
                # Skip if already absolute or has special prefix (like docker://[...]:)
                if path.startswith("/") or path.startswith("["):
                    continue
                # Resolve relative path
                if path == "." or path == "":
                    result[key] = str(self.working_dir)
                else:
                    clean_path = path.lstrip("./")
                    result[key] = str(self.working_dir / clean_path)
        return result

    def _format_tool_history_lines(self, tool_call: Any) -> list[str]:
        """Convert stored ToolCall data into RichLog-friendly summary lines."""

        lines: list[str] = []
        seen: set[str] = set()

        def add_line(value: str) -> None:
            normalized = value.strip()
            if not normalized or normalized in seen:
                return
            lines.append(normalized)
            seen.add(normalized)

        error = getattr(tool_call, "error", None)
        if error:
            add_line(f"{TOOL_ERROR_SENTINEL} {str(error).strip()}")

        summary = getattr(tool_call, "result_summary", None)
        if summary:
            # Use result_summary (matches real-time display from StyleFormatter)
            add_line(str(summary).strip())
        else:
            # Only fall back to truncated raw_result if no summary available
            raw_result = getattr(tool_call, "result", None)
            snippet = self._truncate_tool_output(raw_result)
            if snippet:
                add_line(snippet)

        if not lines:
            add_line("✓ Tool completed")
        return lines

    @staticmethod
    def _truncate_tool_output(raw_result: Any, max_lines: int = 6, max_chars: int = 400) -> str:
        """Trim long stored tool outputs for concise replay."""

        if raw_result is None:
            return ""

        text = str(raw_result).strip()
        if not text:
            return ""

        lines = [line.rstrip() for line in text.splitlines()]
        truncated = False
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated = True
        snippet = "\n".join(lines)
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rstrip()
            truncated = True
        if truncated:
            snippet = f"{snippet}\n... (truncated)"
        return snippet.strip()

    def _get_model_config_snapshot(self) -> dict[str, dict[str, str]]:
        """Return current model configuration details for the UI."""
        config = self.config_manager.get_config()

        try:
            from swecli.config import get_model_registry

            registry = get_model_registry()
        except Exception:  # pragma: no cover - defensive
            registry = None

        def resolve(provider_id: Optional[str], model_id: Optional[str]) -> dict[str, str]:
            if not provider_id or not model_id:
                return {}

            provider_display = provider_id.capitalize()
            model_display = model_id

            if registry is not None:
                provider_info = registry.get_provider(provider_id)
                if provider_info:
                    provider_display = provider_info.name
                found = registry.find_model_by_id(model_id)
                if found:
                    _, _, model_info = found
                    model_display = model_info.name
            else:
                if "/" in model_id:
                    model_display = model_id.split("/")[-1]

            return {
                "provider": provider_id,
                "provider_display": provider_display,
                "model": model_id,
                "model_display": model_display,
            }

        snapshot: dict[str, dict[str, str]] = {}
        snapshot["normal"] = resolve(config.model_provider, config.model)

        thinking_entry = resolve(config.model_thinking_provider, config.model_thinking)
        if thinking_entry:
            snapshot["thinking"] = thinking_entry

        vision_entry = resolve(config.model_vlm_provider, config.model_vlm)
        if vision_entry:
            snapshot["vision"] = vision_entry

        return snapshot

    async def _apply_model_selection(self, slot: str, provider_id: str, model_id: str):
        """Apply a model selection coming from the Textual UI."""
        result = await asyncio.to_thread(
            self.repl.config_commands._switch_to_model,
            provider_id,
            model_id,
            slot,
        )
        if result.success:
            # Rebuild agents with new config (needed for API key changes)
            await asyncio.to_thread(self.repl.rebuild_agents)
            self._refresh_ui_config()
        return result

    def _configure_session(self, resume: Optional[str], continue_session: bool) -> None:
        """Prepare session state mirroring CLI semantics."""

        if resume:
            self.session_manager.load_session(resume)
            return

        if continue_session:
            loaded = self.session_manager.load_latest_session(self.working_dir)
            if loaded:
                return

        self.session_manager.create_session(working_directory=str(self.working_dir))

    def get_queue_size(self) -> int:
        """Get number of messages waiting in queue."""
        return self._pending.qsize()

    def _notify_queue_update(self, from_ui_thread: bool = False) -> None:
        """Notify UI of queue size change.

        Args:
            from_ui_thread: If True, we're already on the UI thread and can call directly
        """
        if self._queue_update_callback:
            size = self.get_queue_size()
            if from_ui_thread:
                # Already on UI thread, call directly
                self._queue_update_callback(size)
            else:
                # On different thread, use call_from_thread
                self.app.call_from_thread(self._queue_update_callback, size)

    def enqueue_message(self, text: str, needs_display: bool = False) -> None:
        """Queue a message from the UI for processing.

        Args:
            text: The message text to queue
            needs_display: If True, the message will be displayed in conversation
                          when it starts processing (because it was queued while
                          another message was being processed)
        """
        item = (text, needs_display)
        # queue.Queue is thread-safe, can be called from any thread
        self._pending.put_nowait(item)

        # Notify UI of queue update (called from UI thread)
        self._notify_queue_update(from_ui_thread=True)

    def _start_message_processor(self) -> None:
        """Start background thread to process messages from the queue."""

        def processor() -> None:
            while not self._processor_stop.is_set():
                try:
                    # Use timeout to allow checking stop event periodically
                    try:
                        message, needs_display = self._pending.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    # Update queue indicator immediately after dequeuing
                    # This ensures the count shows only messages WAITING to be processed,
                    # not the one currently being processed
                    self._notify_queue_update(from_ui_thread=False)

                    is_command = message.startswith("/")

                    # Start spinner for non-command messages (ensures spinner runs for queued messages)
                    if not is_command:
                        self.app.call_from_thread(self.app._start_local_spinner)

                    # Display user message if it was queued (not shown yet)
                    if needs_display and not is_command:
                        self.app.call_from_thread(
                            self.app.conversation.add_user_message, message
                        )

                    try:
                        if is_command:
                            self._run_command(message)
                        else:
                            new_messages = self._run_query(message)
                            if new_messages:
                                self.app.call_from_thread(self._render_responses, new_messages)
                    except Exception as exc:  # pragma: no cover - defensive guard
                        if is_command:
                            self.app.call_from_thread(self.app.conversation.add_error, str(exc))
                        else:
                            self.app.call_from_thread(self.app.notify_processing_error, str(exc))
                    finally:
                        if not is_command:
                            self.app.call_from_thread(self.app.notify_processing_complete)
                        self._pending.task_done()
                        # Notify UI of queue update after processing
                        if self._queue_update_callback:
                            self.app.call_from_thread(
                                self._queue_update_callback, self._pending.qsize()
                            )
                except Exception:  # pragma: no cover - defensive
                    continue  # Keep processing on any unexpected error

        self._processor_thread = threading.Thread(target=processor, daemon=True, name="message-processor")
        self._processor_thread.start()

    def _stop_message_processor(self) -> None:
        """Stop the background message processor thread."""
        if self._processor_thread is not None:
            self._processor_stop.set()
            self._processor_thread.join(timeout=2.0)
            self._processor_thread = None

    def _run_query(self, message: str) -> list[ChatMessage]:
        """Execute a user query via the REPL and return new session messages."""
        import traceback

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
                if hasattr(self.app, 'conversation') and self.app.conversation is not None:
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
            console = self.repl.console
            original_print = console.print
            original_log = getattr(console, "log", None)

            # Restore original print/log functions (bypass bridge)
            console.print = self._original_console_print
            if original_log and self._original_console_log:
                console.log = self._original_console_log

            try:
                # Process query with UI callback for real-time display
                if hasattr(self.repl, '_process_query_with_callback'):
                    self.repl._process_query_with_callback(message, ui_callback)
                else:
                    # Fallback to normal processing if callback method doesn't exist
                    self.repl._process_query(message)
            finally:
                # Restore bridge
                console.print = original_print
                if original_log:
                    console.log = original_log

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
            self._enqueue_console_text(error_msg)
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

        # Switch to NORMAL mode
        self.repl.mode_manager.set_mode(OperationMode.NORMAL)
        self.repl.agent = self.repl.normal_agent

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

        stripped = command.strip()
        lowered = stripped.lower()

        # Background auto-connect trigger
        if lowered.startswith("/mcp autoconnect"):
            if self._connect_inflight:
                self._enqueue_console_text(
                    "[dim]MCP auto-connect already running...[/dim]"
                )
            else:
                self._enqueue_console_text(
                    "[cyan]Starting MCP auto-connect in the background...[/cyan]"
                )
                self._start_mcp_connect_thread(force=True)
            return

        # Special handling for /mcp view command - use Textual modal instead of prompt_toolkit
        if lowered.startswith("/mcp view "):
            self._handle_mcp_view_command(command)
            return

        # Special handling for /mcp connect - use Textual spinner
        if lowered.startswith("/mcp connect "):
            self._handle_mcp_connect_command(command)
            return

        # Special handling for /resolve-issue - use TextualUICallback for proper display
        if lowered.startswith("/resolve-issue"):
            self._handle_resolve_issue_command(command)
            return

        # Special handling for /paper2code - use TextualUICallback for proper display
        if lowered.startswith("/paper2code"):
            self._handle_paper2code_command(command)
            return

        with self.repl.console.capture() as capture:
            self.repl._handle_command(command)
        output = capture.get()
        if output.strip():
            self._enqueue_console_text(output)
        self._refresh_ui_config()

    def _handle_mcp_view_command(self, command: str) -> None:
        """Handle /mcp view command with Textual-native modal.

        Args:
            command: The full command (e.g., "/mcp view server_name")
        """
        import shlex
        from io import StringIO
        from rich.console import Console as RichConsole

        def _emit_error(message: str) -> None:
            """Render a Rich-styled error message into the conversation."""
            string_io = StringIO()
            temp_console = RichConsole(file=string_io, force_terminal=True)
            temp_console.print(message)
            self._enqueue_console_text(string_io.getvalue())

        try:
            raw_parts = shlex.split(command)
        except ValueError:
            raw_parts = command.strip().split()

        if len(raw_parts) < 3:
            _emit_error("[red]Error: Server name required for /mcp view[/red]")
            return

        server_name = " ".join(raw_parts[2:]).strip()
        if not server_name:
            _emit_error("[red]Error: Server name required for /mcp view[/red]")
            return

        mcp_manager = getattr(self.repl, "mcp_manager", None)
        if mcp_manager is None:
            _emit_error("[red]Error: MCP manager is not available in this session[/red]")
            return

        try:
            servers = mcp_manager.list_servers()
        except Exception as exc:  # pragma: no cover - defensive
            _emit_error(f"[red]Error: Unable to load MCP servers ({exc})[/red]")
            return

        if server_name not in servers:
            _emit_error(f"[red]Error: Server '{server_name}' not found in configuration[/red]")
            return

        server_config = servers[server_name]
        is_connected = mcp_manager.is_connected(server_name)
        tools = mcp_manager.get_server_tools(server_name) if is_connected else []

        # Build elegant panel content for the conversation log
        from rich import box
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        info_table = Table(show_header=False, box=None, padding=(0, 1))
        info_table.add_column("Property", style="cyan", no_wrap=True)
        info_table.add_column("Value")

        status_text = (
            Text("Connected", style="bold green")
            if is_connected
            else Text("Disconnected", style="dim")
        )
        info_table.add_row("Status", status_text)

        cmd_text = server_config.command or "unknown"
        info_table.add_row("Command", cmd_text)

        if server_config.args:
            args_text = " ".join(server_config.args)
            if len(args_text) > 80:
                args_text = args_text[:77] + "..."
            info_table.add_row("Args", args_text)

        transport_text = server_config.transport or "stdio"
        info_table.add_row("Transport", transport_text)

        from swecli.core.context_engineering.mcp.config import get_config_path, get_project_config_path

        config_location = ""
        try:
            project_config = get_project_config_path(getattr(mcp_manager, "working_dir", None))
        except Exception:
            project_config = None

        if project_config:
            config_location = f"{project_config} [project]"
        else:
            try:
                config_location = str(get_config_path())
            except Exception:
                config_location = "Unknown"

        info_table.add_row("Config", Text(config_location, style="dim"))

        capabilities: list[str] = []
        if is_connected and tools:
            capabilities.append("tools")
        if capabilities:
            info_table.add_row("Capabilities", " · ".join(capabilities))

        enabled_text = (
            Text("Yes", style="green")
            if server_config.enabled
            else Text("No", style="red")
        )
        info_table.add_row("Enabled", enabled_text)

        auto_start_text = (
            Text("Yes", style="green")
            if server_config.auto_start
            else Text("No", style="dim")
        )
        info_table.add_row("Auto-start", auto_start_text)

        if server_config.env:
            env_lines = "\n".join(f"{key}={value}" for key, value in server_config.env.items())
            info_table.add_row("Environment", env_lines)

        if is_connected:
            info_table.add_row("Tools", f"{len(tools)} available")

        tools_content = None
        if is_connected and tools:
            tools_table = Table(show_header=True, box=box.SIMPLE, padding=(0, 1))
            tools_table.add_column("Tool Name", style="cyan")
            tools_table.add_column("Description", style="white")

            for tool in tools[:10]:
                tool_name = tool.get("name", "unknown")
                tool_desc = tool.get("description", "")
                if len(tool_desc) > 60:
                    tool_desc = tool_desc[:57] + "..."
                tools_table.add_row(tool_name, tool_desc)

            if len(tools) > 10:
                tools_table.add_row(f"... and {len(tools) - 10} more", "", style="dim")

            tools_content = tools_table

        title = f"MCP Server: {server_name}"
        main_panel = Panel(
            info_table,
            title=title,
            title_align="left",
            border_style="bright_cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )

        self._enqueue_console_text("\n")

        string_io = StringIO()
        temp_console = RichConsole(file=string_io, force_terminal=True, width=100)
        temp_console.print(main_panel)

        if tools_content:
            temp_console.print("\n")
            tools_panel = Panel(
                tools_content,
                title="Available Tools",
                title_align="left",
                border_style="green",
                box=box.ROUNDED,
                padding=(1, 2),
            )
            temp_console.print(tools_panel)

        temp_console.print("\n[dim]Available actions:[/dim]")
        if is_connected:
            temp_console.print(f"  [cyan]/mcp disconnect {server_name}[/cyan] - Disconnect from server")
            temp_console.print(f"  [cyan]/mcp tools {server_name}[/cyan] - List all tools")
        else:
            temp_console.print(f"  [cyan]/mcp connect {server_name}[/cyan] - Connect to server")

        if server_config.enabled:
            temp_console.print(f"  [cyan]/mcp disable {server_name}[/cyan] - Disable auto-start")
        else:
            temp_console.print(f"  [cyan]/mcp enable {server_name}[/cyan] - Enable auto-start")

        output = string_io.getvalue()
        self._enqueue_console_text(output)

    def _handle_mcp_connect_command(self, command: str) -> None:
        """Handle /mcp connect with Textual spinner.

        Args:
            command: The full command (e.g., "/mcp connect github")
        """
        from swecli.ui_textual.controllers.mcp_command_controller import MCPCommandController

        controller = MCPCommandController(self.app, self.repl)
        controller.handle_connect(command)

    def _handle_resolve_issue_command(self, command: str) -> None:
        """Handle /resolve-issue command with TextualUICallback for proper display.

        Args:
            command: The full command (e.g., "/resolve-issue https://github.com/owner/repo/issues/123")
        """
        from io import StringIO
        from rich.console import Console as RichConsole

        # Create UI callback for real-time tool display
        conversation_widget = None
        try:
            from swecli.ui_textual.chat_app import ConversationLog
            conversation_widget = self.app.query_one("#conversation", ConversationLog)
        except Exception:
            if hasattr(self.app, 'conversation') and self.app.conversation is not None:
                conversation_widget = self.app.conversation

        ui_callback = None
        if conversation_widget is not None:
            from swecli.ui_textual.ui_callback import TextualUICallback
            ui_callback = TextualUICallback(conversation_widget, self.app, self.working_dir)

        # Capture any console output during execution
        with self.repl.console.capture() as capture:
            self.repl.tool_commands.resolve_issue(command, ui_callback=ui_callback)

        output = capture.get()
        if output.strip():
            self._enqueue_console_text(output)

    def _handle_paper2code_command(self, command: str) -> None:
        """Handle /paper2code command with TextualUICallback for proper display.

        Args:
            command: The full command (e.g., "/paper2code path/to/paper.pdf")
        """
        # Create UI callback for real-time tool display
        conversation_widget = None
        try:
            from swecli.ui_textual.chat_app import ConversationLog
            conversation_widget = self.app.query_one("#conversation", ConversationLog)
        except Exception:
            if hasattr(self.app, 'conversation') and self.app.conversation is not None:
                conversation_widget = self.app.conversation

        ui_callback = None
        if conversation_widget is not None:
            from swecli.ui_textual.ui_callback import TextualUICallback
            ui_callback = TextualUICallback(conversation_widget, self.app, self.working_dir)

        # Capture any console output during execution
        with self.repl.console.capture() as capture:
            self.repl.tool_commands.paper2code(command, ui_callback=ui_callback)

        output = capture.get()
        if output.strip():
            self._enqueue_console_text(output)

    def _handle_interrupt(self) -> bool:
        """Handle interrupt request from UI (ESC key press).

        Returns:
            True if interrupt was requested, False if no task is running
        """
        if hasattr(self.repl, "query_processor") and self.repl.query_processor:
            return self.repl.query_processor.request_interrupt()
        return False

    def _cycle_mode(self) -> str:
        """Toggle between NORMAL and PLAN modes and return the active mode."""

        current = self.repl.mode_manager.current_mode
        from swecli.core.runtime import OperationMode

        new_mode = (
            OperationMode.PLAN
            if current == OperationMode.NORMAL
            else OperationMode.NORMAL
        )

        self.repl.mode_manager.set_mode(new_mode)
        if new_mode == OperationMode.PLAN:
            self.repl.agent = self.repl.planning_agent
        else:
            self.repl.agent = self.repl.normal_agent

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
                        self._last_assistant_message_normalized = normalized
                else:
                    self._last_assistant_message_normalized = content if content else None

                # Only render assistant messages that DON'T have tool calls
                # Messages with tool calls were already displayed in real-time by callbacks
                has_tool_calls = getattr(msg, "tool_calls", None) and len(msg.tool_calls) > 0

                if content and not has_tool_calls:
                    self.app.conversation.add_assistant_message(msg.content)
                    if hasattr(self.app, "record_assistant_message"):
                        self.app.record_assistant_message(msg.content)
                    if hasattr(self.app, "_last_rendered_assistant"):
                        self.app._last_rendered_assistant = content
                    self._last_assistant_message = content
                    self._suppress_console_duplicate = True
                    assistant_text_rendered = True

                # Skip rendering messages with tool calls - already shown in real-time
            elif msg.role == Role.SYSTEM:
                self.app.conversation.add_system_message(msg.content)
            # Skip USER messages - they're already displayed by the UI when user types them

        if buffer_started and hasattr(self.app, "stop_console_buffer"):
            self.app.stop_console_buffer()

    def _render_console_output(self, text: str) -> None:
        """Render console output captured from REPL commands/processings."""

        normalized = self._normalize_console_text(text)
        renderables = list(self._ansi_decoder.decode(normalized))
        if not renderables:
            return
        for renderable in renderables:
            if isinstance(renderable, Text):
                plain = renderable.plain.strip()
                if not plain:
                    continue
                if self._is_spinner_text(plain) or self._is_spinner_tip(plain):
                    continue
                normalized_plain = plain.strip()
                if hasattr(self.app, "_normalize_paragraph"):
                    normalized_plain = self.app._normalize_paragraph(plain)
                pending = getattr(self.app, "_pending_assistant_normalized", None)
                targets = [value for value in (pending, self._last_assistant_message_normalized) if value]
                if self._suppress_console_duplicate and normalized_plain and targets:
                    if any(normalized_plain == target for target in targets):
                        continue
                if plain == self._last_console_line:
                    continue
                self._last_console_line = plain
            else:
                self._last_console_line = None

            if hasattr(self.app, "render_console_output"):
                self.app.render_console_output(renderable)
            else:
                self.app.conversation.write(renderable)
        if not isinstance(renderables[-1], Text):
            self._last_console_line = None
        if self._suppress_console_duplicate:
            self._suppress_console_duplicate = False

        if hasattr(self.app, "stop_console_buffer"):
            self.app.stop_console_buffer()

    @staticmethod
    def _normalize_console_text(text: str) -> str:
        """Collapse carriage-return spinner updates into a single line."""

        if "\r" not in text:
            return text

        lines = text.split("\n")
        for index, line in enumerate(lines):
            if "\r" in line:
                lines[index] = line.split("\r")[-1]
        return "\n".join(lines)

    @staticmethod
    def _clean_tool_summary(summary: str) -> str:
        """Normalize tool summary text for assistant follow-up."""

        cleaned = summary.strip()
        if not cleaned:
            return ""

        if cleaned.lower().startswith("found") and ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1].strip()

        cleaned = cleaned.strip(". ")
        if cleaned:
            return cleaned
        return summary.strip()

    @staticmethod
    def _is_spinner_text(plain: str) -> bool:
        """Return True if the console line appears to be a spinner update."""

        if not plain:
            return False

        first = plain[0]
        # Braille spinner characters live in the Unicode Braille block.
        if 0x2800 <= ord(first) <= 0x28FF:
            return True

        return False

    @staticmethod
    def _is_spinner_tip(plain: str) -> bool:
        """Return True if line looks like a spinner tip."""

        if not plain:
            return False

        normalized = plain.replace("⎿", "").strip().lower()
        return normalized.startswith("tip:")

    def run(self) -> None:
        """Launch the Textual application and background consumer."""

        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_app())
        finally:
            _reset_terminal_mouse_mode()  # Ensure mouse mode is disabled
            self.repl._cleanup()
            with contextlib.suppress(RuntimeError):
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            asyncio.set_event_loop(None)
            self._loop.close()

    async def _run_app(self) -> None:
        """Run Textual app alongside background processing tasks."""

        # Start message processor thread (uses queue.Queue, not asyncio)
        self._start_message_processor()
        self._console_task = asyncio.create_task(self._drain_console_queue())
        try:
            # Use alternate screen mode (inline=False) for clean TUI with no terminal noise
            # Enable mouse for scroll support; text selection requires Option/Alt + drag
            await self.app.run_async(inline=False, mouse=False)
        finally:
            # Stop message processor thread
            self._stop_message_processor()
            # Cancel console task
            if self._console_task:
                self._console_task.cancel()
                await asyncio.gather(self._console_task, return_exceptions=True)

    def _notify_manual_mcp_connect(self) -> None:
        """Inform users how to connect MCP servers when auto-connect is disabled."""
        manager = getattr(self.repl, "mcp_manager", None)
        has_servers = False
        if manager is not None:
            try:
                has_servers = bool(manager.list_servers())
            except Exception:
                has_servers = False
        if not has_servers:
            return

        message = (
            "Tip: MCP servers are not auto-connected. "
            "Run /mcp autoconnect to connect in the background "
            "or /mcp connect <name> for a specific server."
        )
        self._enqueue_console_text(message)

    def _start_mcp_connect_thread(self, force: bool = False) -> None:
        """Queue MCP auto-connect after the UI has rendered."""
        if (not self._auto_connect_mcp and not force) or self._connect_inflight:
            return

        self._connect_inflight = True

        delay = 0.5 if not force else 0.0
        try:
            if delay > 0:
                self._loop.call_later(delay, self._launch_mcp_autoconnect)
            else:
                self._loop.call_soon(self._launch_mcp_autoconnect)
        except RuntimeError:
            self._launch_mcp_autoconnect()

    def _launch_mcp_autoconnect(self) -> None:
        """Trigger MCP auto-connect using the manager's background loop."""
        manager = getattr(self.repl, "mcp_manager", None)
        if manager is None:
            self._connect_inflight = False
            return

        def handle_completion(result: Optional[dict[str, bool]]) -> None:
            def finalize() -> None:
                self._connect_inflight = False
                if result is None:
                    self._enqueue_console_text(
                        "[yellow]Warning: MCP auto-connect failed.[/yellow]"
                    )
                    return
                if not result:
                    self._enqueue_console_text(
                        "[dim]MCP auto-connect completed; no enabled servers were found.[/dim]"
                    )
                    return

                if result:
                    successes = [name for name, ok in result.items() if ok]
                    failures = [name for name, ok in result.items() if not ok]
                    lines: list[str] = []
                    if successes:
                        lines.append(
                            "[green]✓ Connected MCP servers:[/green] "
                            + ", ".join(successes)
                        )
                    if failures:
                        lines.append(
                            "[red]✗ Failed MCP servers:[/red] "
                            + ", ".join(failures)
                        )
                    if lines:
                        self._enqueue_console_text("\n".join(lines))

                    refresh_cb = getattr(self.repl, "_refresh_runtime_tooling", None)
                    if callable(refresh_cb):
                        refresh_cb()
                    self._refresh_ui_config()

            self._loop.call_soon_threadsafe(finalize)

        try:
            manager.connect_enabled_servers_background(on_complete=handle_completion)
        except Exception as exc:  # pragma: no cover - defensive
            self._connect_inflight = False
            self._enqueue_console_text(
                f"[yellow]Warning: MCP auto-connect could not start ({exc}).[/yellow]"
            )

    def _install_console_bridge(self) -> None:
        """Mirror console prints/logs into the Textual conversation."""

        console = self.repl.console
        self._original_console_print = getattr(console, "print")
        self._original_console_log = getattr(console, "log", None)

        def bridge_print(*args, **kwargs):
            with console.capture() as capture:
                self._original_console_print(*args, **kwargs)
            text = capture.get()
            if text.strip():
                self._enqueue_console_text(text)

        console.print = bridge_print  # type: ignore[assignment]

        if self._original_console_log is not None:
            def bridge_log(*args, **kwargs):
                with console.capture() as capture:
                    self._original_console_log(*args, **kwargs)
                text = capture.get()
                if text.strip():
                    self._enqueue_console_text(text)

            console.log = bridge_log  # type: ignore[assignment]

    def _enqueue_console_text(self, text: str) -> None:
        if not text:
            return

        if hasattr(self.app, "_normalize_paragraph"):
            normalized = self.app._normalize_paragraph(text)
            last_assistant = getattr(self.app, "_last_assistant_normalized", None)
            if normalized and last_assistant and normalized == last_assistant:
                return

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            self._console_queue.put_nowait(text)
        elif self._loop.is_running():
            self._loop.call_soon_threadsafe(self._console_queue.put_nowait, text)
        else:
            self._console_queue.put_nowait(text)

    async def _drain_console_queue(self) -> None:
        try:
            while True:
                text = await self._console_queue.get()
                self._render_console_output(text)
                self._console_queue.task_done()
        except asyncio.CancelledError:  # pragma: no cover - task shutdown
            return


def launch_textual_cli(message=None, **kwargs) -> None:
    """Public helper for launching the Textual UI from external callers.

    Args:
        message: Optional message to process automatically
        **kwargs: Additional arguments passed to TextualRunner
    """

    if "auto_connect_mcp" not in kwargs:
        auto_env = os.getenv("SWECLI_MCP_AUTOCONNECT", "").strip().lower()
        if auto_env in {"1", "true", "yes", "on"}:
            kwargs["auto_connect_mcp"] = True

    runner = TextualRunner(**kwargs)

    # If a message is provided, enqueue it for processing
    if message:
        runner.enqueue_message(message)

    runner.run()


if __name__ == "__main__":
    launch_textual_cli()
