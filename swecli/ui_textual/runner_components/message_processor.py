"""Message processing engine for TextualRunner.

This module handles the background message processing thread, queue management,
and orchestrating the execution of commands and queries via callbacks.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Optional

from swecli.models.message import ChatMessage


class MessageProcessor:
    """Manages the background message processing loop and queue."""

    def __init__(
        self,
        app: Any,
        callbacks: dict[str, Any],
    ) -> None:
        """Initialize the processor.

        Args:
            app: The Textual app instance.
            callbacks: Dictionary containing handler functions:
                - handle_command: Callable[[str], None]
                - handle_query: Callable[[str], list[ChatMessage]]
                - render_responses: Callable[[list[ChatMessage]], None]
                - on_error: Callable[[str], None]  # Generic errors
                - on_command_error: Callable[[str], None] # Command-specific errors
        """
        self._app = app
        self._callbacks = callbacks
        
        # Queue holds tuples of (message, needs_display)
        self._pending: queue.Queue[tuple[str, bool]] = queue.Queue()

        self._processor_thread: threading.Thread | None = None
        self._processor_stop = threading.Event()
        self._message_ready = threading.Event()  # Signal when message is enqueued
        
        # Callback to update UI queue indicator
        self._queue_update_callback: Callable[[int], None] | None = None
        if hasattr(app, "update_queue_indicator"):
            self._queue_update_callback = app.update_queue_indicator

    def set_app(self, app: Any) -> None:
        """Set the Textual app instance."""
        self._app = app
        if hasattr(app, "update_queue_indicator"):
            self._queue_update_callback = app.update_queue_indicator


    def get_queue_size(self) -> int:
        """Get number of messages waiting in queue."""
        return self._pending.qsize()

    def enqueue_message(self, text: str, needs_display: bool = False) -> None:
        """Queue a message for processing.

        Args:
            text: The message text.
            needs_display: Whether to display the message in the UI when processing starts.
        """
        item = (text, needs_display)
        self._pending.put_nowait(item)
        self._message_ready.set()  # Wake up processor immediately
        self._notify_queue_update(from_ui_thread=True)

    def start(self) -> None:
        """Start the background processor thread."""
        if self._processor_thread is not None:
            return

        self._processor_stop.clear()
        self._processor_thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="message-processor"
        )
        self._processor_thread.start()

    def stop(self) -> None:
        """Stop the background processor thread."""
        if self._processor_thread is not None:
            self._processor_stop.set()
            self._message_ready.set()  # Wake up thread so it can exit
            self._processor_thread.join(timeout=2.0)
            self._processor_thread = None

    def _notify_queue_update(self, from_ui_thread: bool = False) -> None:
        """Notify UI of queue size change."""
        if not self._queue_update_callback:
            return
            
        size = self.get_queue_size()
        if from_ui_thread:
            self._queue_update_callback(size)
        else:
            self._app.call_from_thread(self._queue_update_callback, size)

    def _run_loop(self) -> None:
        """Main processing loop running in background thread."""
        while not self._processor_stop.is_set():
            try:
                # Wait for message signal or periodic check for stop
                self._message_ready.wait(timeout=0.5)
                self._message_ready.clear()

                try:
                    message, needs_display = self._pending.get_nowait()
                except queue.Empty:
                    continue

                # Update indicator to show waiting count (excluding current)
                self._notify_queue_update(from_ui_thread=False)

                is_command = message.startswith("/")

                # Start local spinner for non-commands
                if not is_command and hasattr(self._app, "_start_local_spinner"):
                    self._app.call_from_thread(self._app._start_local_spinner)

                # Display user message if needed (queued while busy)
                if needs_display and not is_command:
                    self._app.call_from_thread(
                        self._app.conversation.add_user_message, message
                    )
                    if hasattr(self._app.conversation, "refresh"):
                        self._app.call_from_thread(self._app.conversation.refresh)

                try:
                    if is_command:
                        handler = self._callbacks.get("handle_command")
                        if handler:
                            handler(message)
                    else:
                        handler = self._callbacks.get("handle_query")
                        render = self._callbacks.get("render_responses")
                        if handler:
                            new_messages = handler(message)
                            if new_messages and render:
                                self._app.call_from_thread(render, new_messages)
                except Exception as exc:  # pragma: no cover - defensive
                    if is_command:
                        err_handler = self._callbacks.get("on_command_error")
                        if err_handler:
                             self._app.call_from_thread(err_handler, str(exc))
                    else:
                        err_handler = self._callbacks.get("on_error")
                        if err_handler:
                             self._app.call_from_thread(err_handler, str(exc))
                finally:
                    self._pending.task_done()
                    
                    # Notify completion if queue empty (for both commands and messages)
                    if self._pending.empty():
                        if hasattr(self._app, "notify_processing_complete"):
                            self._app.call_from_thread(self._app.notify_processing_complete)
                            
                    # Update indicator
                    self._notify_queue_update(from_ui_thread=False)

            except Exception:  # pragma: no cover - defensive
                continue
