"""UI callback for real-time tool call display in Textual UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from swecli.ui_textual.formatters.style_formatter import StyleFormatter
from swecli.ui_textual.utils.tool_display import build_tool_call_text

# Path argument keys that should be resolved to absolute paths
_PATH_ARG_KEYS = {"path", "file_path", "working_dir", "directory", "dir", "target"}


class TextualUICallback:
    """Callback for real-time display of agent actions in Textual UI."""

    def __init__(self, conversation_log, chat_app=None, working_dir: Optional[Path] = None):
        """Initialize the UI callback.

        Args:
            conversation_log: The ConversationLog widget to display messages
            chat_app: The main chat app (SWECLIChatApp instance) for controlling processing state
            working_dir: Working directory for resolving relative paths in tool displays
        """
        self.conversation = conversation_log
        self.chat_app = chat_app
        # chat_app IS the Textual App instance itself, not a wrapper
        self._app = chat_app
        self.formatter = StyleFormatter()
        self._current_thinking = False
        self._streaming_bash_box = False  # True when streaming bash output to box
        self._pending_bash_start = False  # True when bash box start is deferred
        self._pending_bash_command = ""  # Command being executed (for VS Code terminal display)
        self._pending_bash_working_dir = "."  # Working directory for bash command
        # Spinner IDs for tracking active spinners via SpinnerService
        self._progress_spinner_id: str = ""
        self._tool_spinner_id: str = ""
        # Buffering for bash output to prevent UI flooding
        self._bash_buffer: list[tuple[str, bool]] = []
        self._last_bash_flush: float = 0
        self._BASH_FLUSH_INTERVAL: float = 0.1  # 100ms
        # Working directory for resolving relative paths
        self._working_dir = working_dir

    def on_thinking_start(self) -> None:
        """Called when the agent starts thinking."""
        self._current_thinking = True

        # The app's built-in spinner should already be running with our custom message
        # We don't need to start another spinner, just note that thinking has started

    def on_thinking_complete(self) -> None:
        """Called when the agent completes thinking."""
        if self._current_thinking:
            # Don't stop the spinner here - let it continue during tool execution
            # The app will stop it when the entire process is complete
            self._current_thinking = False

    def on_assistant_message(self, content: str) -> None:
        """Called when assistant provides a message before tool execution.

        Args:
            content: The assistant's message/thinking
        """
        if content and content.strip():
            # Stop spinner before showing assistant message
            # Note: Only call _stop_local_spinner which goes through SpinnerController
            # with grace period. Don't call conversation.stop_spinner directly as it
            # bypasses the grace period and removes the spinner immediately.
            if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
                self._run_on_ui(self.chat_app._stop_local_spinner)

            # Display the assistant's thinking/message
            if hasattr(self.conversation, 'add_assistant_message'):
                self._run_on_ui(self.conversation.add_assistant_message, content)

    def on_message(self, message: str) -> None:
        """Called to display a simple progress message (no spinner).

        Args:
            message: The message to display
        """
        if hasattr(self.conversation, 'add_system_message'):
            self._run_on_ui(self.conversation.add_system_message, message)

    def on_progress_start(self, message: str) -> None:
        """Called when a progress operation starts (shows spinner).

        Args:
            message: The progress message to display with spinner
        """
        # Use SpinnerService for unified spinner management
        if self._app is not None and hasattr(self._app, 'spinner_service'):
            self._progress_spinner_id = self._app.spinner_service.start(message)
        else:
            # Fallback to direct calls if SpinnerService not available
            from rich.text import Text

            display_text = Text(message, style="white")
            if hasattr(self.conversation, 'add_tool_call') and self._app is not None:
                self._app.call_from_thread(self.conversation.add_tool_call, display_text)
            if hasattr(self.conversation, 'start_tool_execution') and self._app is not None:
                self._app.call_from_thread(self.conversation.start_tool_execution)

    def on_progress_update(self, message: str) -> None:
        """Update progress text in-place (same line, keeps spinner running).

        Use this for multi-step progress where you want to update the text
        without creating a new line. The spinner and timer continue running.

        Args:
            message: New progress message to display
        """
        # Use SpinnerService for unified spinner management
        if self._progress_spinner_id and self._app is not None and hasattr(self._app, 'spinner_service'):
            self._app.spinner_service.update(self._progress_spinner_id, message)
        else:
            # Fallback to direct calls if SpinnerService not available
            from rich.text import Text

            display_text = Text(message, style="white")
            if hasattr(self.conversation, 'update_progress_text'):
                self._run_on_ui(self.conversation.update_progress_text, display_text)

    def on_progress_complete(self, message: str = "", success: bool = True) -> None:
        """Called when a progress operation completes.

        Args:
            message: Optional result message to display
            success: Whether the operation succeeded (affects bullet color)
        """
        # Use SpinnerService for unified spinner management
        if self._progress_spinner_id and self._app is not None and hasattr(self._app, 'spinner_service'):
            self._app.spinner_service.stop(self._progress_spinner_id, success, message)
            self._progress_spinner_id = ""
        else:
            # Fallback to direct calls if SpinnerService not available
            from rich.text import Text

            # Stop spinner (shows green/red bullet based on success)
            if hasattr(self.conversation, 'stop_tool_execution'):
                self._run_on_ui(lambda: self.conversation.stop_tool_execution(success))

            # Show result line (if message provided)
            if message:
                result_line = Text("  ⎿  ", style="#a0a4ad")
                result_line.append(message, style="#a0a4ad")
                self._run_on_ui(self.conversation.write, result_line)

    def on_interrupt(self) -> None:
        """Called when execution is interrupted by user.

        Displays the interrupt message directly by replacing the blank line after user prompt.
        """
        # Stop any active spinners via SpinnerService
        if self._app is not None and hasattr(self._app, 'spinner_service'):
            if self._tool_spinner_id:
                self._app.spinner_service.stop(self._tool_spinner_id, success=False)
                self._tool_spinner_id = ""
            if self._progress_spinner_id:
                self._app.spinner_service.stop(self._progress_spinner_id, success=False)
                self._progress_spinner_id = ""

        # Stop spinner first - this removes spinner lines but leaves the blank line after user prompt
        if hasattr(self.conversation, 'stop_spinner'):
            self._run_on_ui(self.conversation.stop_spinner)
        if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
            self._run_on_ui(self.chat_app._stop_local_spinner)

        # The key insight: after user message, there's a blank line (added by add_user_message)
        # After stopping spinner, this blank line is the last line
        # We need to remove it using _truncate_from to properly update widget state
        def write_interrupt_replacing_blank_line():
            from rich.text import Text

            # Check if we have lines and last line is blank
            if hasattr(self.conversation, 'lines') and len(self.conversation.lines) > 0:
                # Check if last line is blank
                last_line = self.conversation.lines[-1]

                # RichLog stores lines as Strip objects, not Text objects
                # A blank line is a Strip with empty segments or a single empty Segment
                is_blank = False

                # Check if it's a Strip object with empty content
                if hasattr(last_line, '_segments'):
                    segments = last_line._segments
                    if len(segments) == 0:
                        is_blank = True
                    elif len(segments) == 1 and segments[0].text == '':
                        is_blank = True
                elif hasattr(last_line, 'plain'):
                    # Fallback for Text objects
                    if last_line.plain.strip() == "":
                        is_blank = True

                if is_blank:
                    # Use _truncate_from to properly remove the blank line and update widget state
                    if hasattr(self.conversation, '_truncate_from'):
                        self.conversation._truncate_from(len(self.conversation.lines) - 1)

            # Now write the interrupt message using shared utility
            from swecli.ui_textual.utils.interrupt_utils import create_interrupt_text, THINKING_INTERRUPT_MESSAGE
            interrupt_line = create_interrupt_text(THINKING_INTERRUPT_MESSAGE)
            self.conversation.write(interrupt_line)

        self._run_on_ui(write_interrupt_replacing_blank_line)

    def on_bash_output_line(self, line: str, is_stderr: bool = False) -> None:
        """Called for each line of bash output during streaming execution.

        Args:
            line: A single line of output from the bash command
            is_stderr: True if this line came from stderr
        """
        import time

        # Lazy start: only open the box when we actually have output
        if self._pending_bash_start:
            self._pending_bash_start = False
            self._streaming_bash_box = True
            if hasattr(self.conversation, 'start_streaming_bash_box'):
                self._run_on_ui(
                    self.conversation.start_streaming_bash_box,
                    self._pending_bash_command,
                    self._pending_bash_working_dir,
                )

        if self._streaming_bash_box and hasattr(self.conversation, 'append_to_streaming_box'):
            # Buffer the output
            self._bash_buffer.append((line, is_stderr))

            # Check if it's time to flush
            now = time.time()
            if now - self._last_bash_flush >= self._BASH_FLUSH_INTERVAL:
                self._flush_bash_buffer()

    def _flush_bash_buffer(self) -> None:
        """Flush buffered bash output to UI."""
        import time

        if not self._bash_buffer:
            return

        # Atomic swap to avoid locking
        chunk = self._bash_buffer
        self._bash_buffer = []
        self._last_bash_flush = time.time()

        def update_ui(chunk_to_process: list[tuple[str, bool]]) -> None:
            if self._streaming_bash_box and hasattr(self.conversation, 'append_to_streaming_box'):
                 for line_content, is_err in chunk_to_process:
                     self.conversation.append_to_streaming_box(line_content, is_err)

        self._run_on_ui(update_ui, chunk)

    def on_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> None:
        """Called when a tool call is about to be executed.

        Args:
            tool_name: Name of the tool being called
            tool_args: Arguments for the tool call
        """
        # Stop thinking spinner if still active
        if self._current_thinking:
            self._run_on_ui(self.conversation.stop_spinner)
            self._current_thinking = False

        if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
            self._run_on_ui(self.chat_app._stop_local_spinner)

        normalized_args = self._normalize_arguments(tool_args)
        # Resolve relative paths to absolute for display
        display_args = self._resolve_paths_in_args(normalized_args)
        display_text = build_tool_call_text(tool_name, display_args)

        # Use SpinnerService for unified spinner management
        if self._app is not None and hasattr(self._app, 'spinner_service'):
            self._tool_spinner_id = self._app.spinner_service.start(display_text)
        else:
            # Fallback to direct calls if SpinnerService not available
            if hasattr(self.conversation, 'add_tool_call') and self._app is not None:
                self._app.call_from_thread(self.conversation.add_tool_call, display_text)
            if hasattr(self.conversation, 'start_tool_execution') and self._app is not None:
                self._app.call_from_thread(self.conversation.start_tool_execution)

        # For bash commands, start streaming box with command info
        if tool_name in ("bash_execute", "run_command"):
            self._pending_bash_command = normalized_args.get("command", "")
            # Get working_dir - try multiple sources
            import os
            working_dir = os.getcwd()  # Default to current working directory

            # Try to get from runner's bash_tool if available
            if self.chat_app and hasattr(self.chat_app, 'runner'):
                runner = self.chat_app.runner
                if hasattr(runner, 'query_processor'):
                    qp = runner.query_processor
                    if hasattr(qp, 'bash_tool') and qp.bash_tool:
                        bash_wd = getattr(qp.bash_tool, 'working_dir', None)
                        if bash_wd:
                            working_dir = str(bash_wd)

            self._pending_bash_working_dir = working_dir

            # Don't start box yet - wait for first output line (lazy start)
            # This prevents empty boxes appearing during approval prompts
            if hasattr(self.conversation, 'start_streaming_bash_box'):
                self._pending_bash_start = True

    def on_tool_result(self, tool_name: str, tool_args: Dict[str, Any], result: Any) -> None:
        """Called when a tool execution completes.

        Args:
            tool_name: Name of the tool that was executed
            tool_args: Arguments that were used
            result: Result of the tool execution (can be dict or string)
        """
        # Handle string results by converting to dict format
        if isinstance(result, str):
            result = {"success": True, "output": result}

        # Stop spinner animation
        # Pass success status to color the bullet (green for success, red for failure)
        success = result.get("success", True) if isinstance(result, dict) else True

        # Use SpinnerService for unified spinner management
        if self._tool_spinner_id and self._app is not None and hasattr(self._app, 'spinner_service'):
            # Stop spinner without result message - results are displayed separately
            self._app.spinner_service.stop(self._tool_spinner_id, success)
            self._tool_spinner_id = ""
        else:
            # Fallback to direct calls if SpinnerService not available
            if hasattr(self.conversation, 'stop_tool_execution'):
                self._run_on_ui(lambda: self.conversation.stop_tool_execution(success))

        # Skip displaying interrupted operations
        # These are already shown by the approval controller interrupt message
        if isinstance(result, dict) and result.get("interrupted"):
            return

        # Skip displaying spawn_subagent results - the command handler shows its own result
        if tool_name == "spawn_subagent":
            return

        # Special handling for bash commands - close streaming box or show summary
        if tool_name in ("bash_execute", "run_command") and isinstance(result, dict):
            is_error = not result.get("success", True)
            exit_code = result.get("exit_code", 1 if is_error else 0)

            # Flush any remaining output in buffer
            self._flush_bash_buffer()

            # Reset pending start flag if it was never triggered (no output)
            self._pending_bash_start = False

            # If streaming box is active, close it
            if self._streaming_bash_box:
                if hasattr(self.conversation, 'close_streaming_bash_box'):
                    self._run_on_ui(self.conversation.close_streaming_bash_box, is_error, exit_code)
                self._streaming_bash_box = False

                # Record summary for history
                stdout = result.get("stdout") or result.get("output") or ""
                # Filter out placeholder messages
                if stdout in ("Command executed", "Command execution failed"):
                    stdout = ""
                if stdout and self.chat_app and hasattr(self.chat_app, "record_tool_summary"):
                    lines = stdout.strip().splitlines()
                    if lines:
                        summary = lines[0][:70] + "..." if len(lines[0]) > 70 else lines[0]
                        if len(lines) > 1:
                            summary += f" ({len(lines)} lines)"
                        self._run_on_ui(self.chat_app.record_tool_summary, tool_name, self._normalize_arguments(tool_args), [summary])

                return

            # Fallback: show terminal box if no streaming was happening (no output case)
            if hasattr(self.conversation, 'add_bash_output_box'):
                import os
                command = self._normalize_arguments(tool_args).get("command", "")
                working_dir = os.getcwd()
                # Combine stdout and stderr for display, avoiding duplicates
                # First try stdout/stderr, then fall back to combined output key
                output_parts = []
                if result.get("stdout"):
                    output_parts.append(result["stdout"])
                if result.get("stderr"):
                    output_parts.append(result["stderr"])
                combined_output = "\n".join(output_parts).strip()
                # Fall back to "output" key if stdout/stderr are empty
                # Filter out placeholder messages that aren't actual command output
                if not combined_output and result.get("output"):
                    output_value = result["output"].strip()
                    if output_value not in ("Command executed", "Command execution failed"):
                        combined_output = output_value
                self._run_on_ui(
                    self.conversation.add_bash_output_box,
                    combined_output,
                    is_error,
                    command,
                    working_dir,
                    0,  # depth
                )

            return

        # Format the result using the Claude-style formatter
        normalized_args = self._normalize_arguments(tool_args)
        formatted = self.formatter.format_tool_result(tool_name, normalized_args, result)

        # Extract the result line(s) from the formatted output
        summary_lines: list[str] = []
        collected_lines: list[str] = []
        if isinstance(formatted, str):
            lines = formatted.splitlines()
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("⎿"):
                    # This is a result line
                    result_text = stripped.lstrip("⎿").strip()
                    if result_text:
                        summary_lines.append(result_text)
                        collected_lines.append(result_text)
        else:
            self._run_on_ui(self.conversation.write, formatted)
            if hasattr(formatted, "renderable") and hasattr(formatted, "title"):
                # Panels typically summarize tool output in title/body; try to capture text
                renderable = getattr(formatted, "renderable", None)
                if isinstance(renderable, str):
                    summary_lines.append(renderable.strip())

        if collected_lines:
            block = "\n".join(collected_lines)
            self._run_on_ui(self.conversation.add_tool_result, block)

        if summary_lines and self.chat_app and hasattr(self.chat_app, "record_tool_summary"):
            self._run_on_ui(self.chat_app.record_tool_summary, tool_name, normalized_args, summary_lines.copy())

        # Auto-refresh todo panel after todo tool execution
        if tool_name in {"write_todos", "update_todo", "complete_todo"}:
            self._refresh_todo_panel()

    def on_nested_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        depth: int,
        parent: str,
    ) -> None:
        """Called when a nested tool call (from subagent) is about to be executed.

        Args:
            tool_name: Name of the tool being called
            tool_args: Arguments for the tool call
            depth: Nesting depth level (1 = direct child of main agent)
            parent: Name/identifier of the parent subagent
        """
        normalized_args = self._normalize_arguments(tool_args)

        # Display nested tool call with indentation (BLOCKING to ensure timer starts before tool executes)
        if hasattr(self.conversation, 'add_nested_tool_call') and self._app is not None:
            display_text = build_tool_call_text(tool_name, normalized_args)
            self._app.call_from_thread(
                self.conversation.add_nested_tool_call,
                display_text,
                depth,
                parent,
            )

    def on_nested_tool_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        depth: int,
        parent: str,
    ) -> None:
        """Called when a nested tool execution (from subagent) completes.

        Args:
            tool_name: Name of the tool that was executed
            tool_args: Arguments that were used
            result: Result of the tool execution (can be dict or string)
            depth: Nesting depth level
            parent: Name/identifier of the parent subagent
        """
        # Handle string results by converting to dict format
        if isinstance(result, str):
            result = {"success": True, "output": result}

        # Skip displaying interrupted operations
        # These are already shown by the approval controller interrupt message
        if isinstance(result, dict) and result.get("interrupted"):
            # Still update the tool call status to show it was interrupted
            # Use BLOCKING call_from_thread to ensure display updates before next tool
            if hasattr(self.conversation, 'complete_nested_tool_call') and self._app is not None:
                self._app.call_from_thread(
                    self.conversation.complete_nested_tool_call,
                    tool_name,
                    depth,
                    parent,
                    False,  # success=False for interrupted
                )
            return

        # Update the nested tool call status to complete
        # Use BLOCKING call_from_thread to ensure each tool's completion is displayed
        # before the next tool starts (fixes "all at once" display issue)
        if hasattr(self.conversation, 'complete_nested_tool_call') and self._app is not None:
            success = result.get("success", False) if isinstance(result, dict) else True
            self._app.call_from_thread(
                self.conversation.complete_nested_tool_call,
                tool_name,
                depth,
                parent,
                success,
            )

        normalized_args = self._normalize_arguments(tool_args)

        # Special handling for todo tools (custom display format with icons)
        if tool_name == "write_todos" and result.get("success"):
            todos = tool_args.get("todos", [])
            self._display_todo_sub_results(todos, depth)
        elif tool_name == "update_todo" and result.get("success"):
            todo_data = result.get("todo", {})
            self._display_todo_update_result(tool_args, todo_data, depth)
        elif tool_name == "complete_todo" and result.get("success"):
            todo_data = result.get("todo", {})
            self._display_todo_complete_result(todo_data, depth)
        elif tool_name in ("bash_execute", "run_command") and isinstance(result, dict):
            # Special handling for bash commands - render in VS Code Terminal style
            # Docker returns "output", local bash returns "stdout"/"stderr"
            stdout = result.get("stdout") or result.get("output") or ""
            # Filter out placeholder messages
            if stdout in ("Command executed", "Command execution failed"):
                stdout = ""
            stderr = result.get("stderr") or ""
            is_error = not result.get("success", True)
            exit_code = result.get("exit_code", 1 if is_error else 0)
            command = normalized_args.get("command", "")

            # Get working_dir from tool args (Docker subagents inject this with prefix)
            working_dir = normalized_args.get("working_dir", ".")

            # Combine stdout and stderr for display, avoiding duplicates
            output = stdout.strip()
            if stderr.strip():
                output = (output + "\n" + stderr.strip()) if output else stderr.strip()

            if hasattr(self.conversation, 'add_nested_bash_output_box'):
                self._run_on_ui(
                    self.conversation.add_nested_bash_output_box,
                    output,
                    is_error,
                    exit_code,
                    command,
                    working_dir,
                    depth,
                )
        else:
            # ALL other tools use unified StyleFormatter (same as main agent)
            self._display_tool_sub_result(tool_name, normalized_args, result, depth)

        # Auto-refresh todo panel after nested todo tool execution
        if tool_name in {"write_todos", "update_todo", "complete_todo"}:
            self._refresh_todo_panel()

    def _display_tool_sub_result(
        self, tool_name: str, tool_args: Dict[str, Any], result: Dict[str, Any], depth: int
    ) -> None:
        """Display tool result using StyleFormatter (same as main agent).

        This ensures subagent results look identical to main agent results.
        No code duplication - reuses the same formatting logic.

        Args:
            tool_name: Name of the tool that was executed
            tool_args: Arguments that were used
            result: Result of the tool execution
            depth: Nesting depth for indentation
        """
        # Skip displaying interrupted operations (safety net - should be caught earlier)
        if isinstance(result, dict) and result.get("interrupted"):
            return

        # Special handling for edit_file - use dedicated diff display with colors
        # This avoids ANSI code stripping that happens in add_nested_tool_sub_results
        if tool_name == "edit_file" and result.get("success"):
            diff_text = result.get("diff", "")
            if diff_text and hasattr(self.conversation, 'add_edit_diff_result'):
                # Show summary line first
                file_path = tool_args.get("file_path", "unknown")
                lines_added = result.get("lines_added", 0) or 0
                lines_removed = result.get("lines_removed", 0) or 0

                def _plural(count: int, singular: str) -> str:
                    return f"{count} {singular}" if count == 1 else f"{count} {singular}s"

                summary = f"Updated {file_path} with {_plural(lines_added, 'addition')} and {_plural(lines_removed, 'removal')}"
                self._run_on_ui(self.conversation.add_nested_tool_sub_results, [summary], depth)
                # Then show colored diff
                self._run_on_ui(self.conversation.add_edit_diff_result, diff_text, depth)
                return
            # Fall through to generic display if no diff

        # Get result lines from StyleFormatter (same code path as main agent)
        if tool_name == "read_file":
            lines = self.formatter._format_read_file_result(tool_args, result)
        elif tool_name == "write_file":
            lines = self.formatter._format_write_file_result(tool_args, result)
        elif tool_name == "edit_file":
            lines = self.formatter._format_edit_file_result(tool_args, result)
        elif tool_name == "search":
            lines = self.formatter._format_search_result(tool_args, result)
        elif tool_name in {"run_command", "bash_execute"}:
            lines = self.formatter._format_shell_result(tool_args, result)
        elif tool_name == "list_files":
            lines = self.formatter._format_list_files_result(tool_args, result)
        elif tool_name == "fetch_url":
            lines = self.formatter._format_fetch_url_result(tool_args, result)
        elif tool_name == "analyze_image":
            lines = self.formatter._format_analyze_image_result(tool_args, result)
        elif tool_name == "get_process_output":
            lines = self.formatter._format_process_output_result(tool_args, result)
        else:
            lines = self.formatter._format_generic_result(tool_name, tool_args, result)

        # Display each line with proper nesting
        if lines and hasattr(self.conversation, 'add_nested_tool_sub_results'):
            self._run_on_ui(self.conversation.add_nested_tool_sub_results, lines, depth)

    def _display_todo_sub_results(self, todos: list, depth: int) -> None:
        """Display nested list of created todos.

        Args:
            todos: List of todo items (dicts with content/status or strings)
            depth: Nesting depth for indentation
        """
        if not todos:
            return

        items = []
        for item in todos:
            if isinstance(item, dict):
                title = item.get("content", "")
                status = item.get("status", "pending")
            else:
                title = str(item)
                status = "pending"

            symbol = {"pending": "○", "in_progress": "▶", "completed": "✓"}.get(status, "○")
            items.append((symbol, title))

        if items and hasattr(self.conversation, 'add_todo_sub_results'):
            self._run_on_ui(self.conversation.add_todo_sub_results, items, depth)

    def _display_todo_update_result(self, args: Dict[str, Any], todo_data: Dict[str, Any], depth: int) -> None:
        """Display what was updated in the todo.

        Args:
            args: Tool arguments (contains status)
            todo_data: The todo data from result
            depth: Nesting depth for indentation
        """
        status = args.get("status", "")
        title = todo_data.get("title", "") or todo_data.get("content", "")

        if not title:
            return

        # Use icons only, no text like "doing:"
        if status in ("in_progress", "doing"):
            line = f"▶ {title}"
        elif status in ("completed", "done"):
            line = f"✓ {title}"
        else:
            line = f"○ {title}"

        if hasattr(self.conversation, 'add_todo_sub_result'):
            self._run_on_ui(self.conversation.add_todo_sub_result, line, depth)

    def _display_todo_complete_result(self, todo_data: Dict[str, Any], depth: int) -> None:
        """Display completed todo.

        Args:
            todo_data: The todo data from result
            depth: Nesting depth for indentation
        """
        title = todo_data.get("title", "") or todo_data.get("content", "")

        if not title:
            return

        if hasattr(self.conversation, 'add_todo_sub_result'):
            self._run_on_ui(self.conversation.add_todo_sub_result, f"✓ {title}", depth)

    def _normalize_arguments(self, tool_args: Any) -> Dict[str, Any]:
        """Ensure tool arguments are represented as a dictionary and normalize URLs for display."""

        if isinstance(tool_args, dict):
            result = tool_args
        elif isinstance(tool_args, str):
            try:
                parsed = json.loads(tool_args)
                if isinstance(parsed, dict):
                    result = parsed
                else:
                    result = {"value": parsed}
            except json.JSONDecodeError:
                result = {"value": tool_args}
        else:
            result = {"value": tool_args}

        # Normalize URLs for display (fix common malformations)
        if "url" in result and isinstance(result["url"], str):
            url = result["url"].strip()
            # Fix: https:/domain.com → https://domain.com
            if url.startswith("https:/") and not url.startswith("https://"):
                result["url"] = url.replace("https:/", "https://", 1)
            elif url.startswith("http:/") and not url.startswith("http://"):
                result["url"] = url.replace("http:/", "http://", 1)
            # Add protocol if missing
            elif not url.startswith(("http://", "https://")):
                result["url"] = f"https://{url}"

        return result

    def _resolve_paths_in_args(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve relative paths to absolute paths for display.

        Args:
            tool_args: Tool arguments dict

        Returns:
            Copy of tool_args with paths resolved to absolute paths
        """
        if self._working_dir is None:
            return tool_args

        result = dict(tool_args)
        for key in _PATH_ARG_KEYS:
            if key in result and isinstance(result[key], str):
                path = result[key]
                # Skip if already absolute or has special prefix (like docker://[...]:)
                if path.startswith("/") or path.startswith("["):
                    continue
                # Resolve relative path
                if path == "." or path == "":
                    result[key] = str(self._working_dir)
                else:
                    clean_path = path.lstrip("./")
                    result[key] = str(self._working_dir / clean_path)
        return result

    def _run_on_ui(self, func, *args, **kwargs) -> None:
        """Execute a function on the Textual UI thread WITHOUT waiting.

        Uses call_soon_threadsafe to schedule work on the event loop
        without blocking the calling thread.
        """
        if self._app is not None:
            # Use call_soon_threadsafe for truly non-blocking UI updates
            loop = getattr(self._app, '_loop', None)
            if loop is not None:
                loop.call_soon_threadsafe(lambda: func(*args, **kwargs))
            else:
                # Fallback to blocking call_from_thread if no loop available
                self._app.call_from_thread(func, *args, **kwargs)
        else:
            func(*args, **kwargs)

    def _run_on_ui_non_blocking(self, func, *args, **kwargs) -> None:
        """Execute a function on the Textual UI thread WITHOUT waiting.

        Note: This is now identical to _run_on_ui. Kept for API compatibility.
        """
        self._run_on_ui(func, *args, **kwargs)

    def _should_skip_due_to_interrupt(self) -> bool:
        """Check if we should skip UI operations due to interrupt.

        Returns:
            True if an interrupt is pending and we should skip UI updates
        """
        if self.chat_app and hasattr(self.chat_app, 'runner'):
            runner = self.chat_app.runner
            if hasattr(runner, 'query_processor'):
                query_processor = runner.query_processor
                if hasattr(query_processor, 'task_monitor'):
                    task_monitor = query_processor.task_monitor
                    if task_monitor and hasattr(task_monitor, 'should_interrupt'):
                        return task_monitor.should_interrupt()
        return False

    def on_debug(self, message: str, prefix: str = "DEBUG") -> None:
        """Called to display debug information about execution flow.

        Args:
            message: The debug message to display
            prefix: Optional prefix for categorizing debug messages
        """
        # Skip debug if interrupted
        if self._should_skip_due_to_interrupt():
            return

        # Display debug message in conversation (non-blocking)
        if hasattr(self.conversation, 'add_debug_message'):
            self._run_on_ui_non_blocking(self.conversation.add_debug_message, message, prefix)

    def _refresh_todo_panel(self) -> None:
        """Refresh the todo panel with latest state."""
        if not self.chat_app:
            return

        try:
            from swecli.ui_textual.widgets.todo_panel import TodoPanel
            panel = self.chat_app.query_one("#todo-panel", TodoPanel)
            self._run_on_ui(panel.refresh_display)
        except Exception:
            # Panel not found or not initialized yet
            pass

    def on_tool_complete(
        self,
        tool_name: str,
        success: bool,
        message: str,
        details: Optional[str] = None,
    ) -> None:
        """Called when ANY tool completes to display result.
        
        This is the standardized method for showing tool completion results.
        Every tool should call this to display its pass/fail status.
        
        Args:
            tool_name: Name of the tool that completed
            success: Whether the tool succeeded
            message: Result message to display
            details: Optional additional details (shown dimmed)
        """
        from swecli.ui_textual.formatters.result_formatter import (
            ToolResultFormatter,
            ResultType,
        )
        
        formatter = ToolResultFormatter()
        
        # Determine result type based on success
        result_type = ResultType.SUCCESS if success else ResultType.ERROR
        
        # Format the result using centralized formatter
        result_text = formatter.format_result(
            message,
            result_type,
            secondary=details,
        )
        
        # Display in conversation
        self._run_on_ui(self.conversation.write, result_text)
