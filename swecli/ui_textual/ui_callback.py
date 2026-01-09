"""UI callback for real-time tool call display in Textual UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from swecli.ui_textual.formatters.style_formatter import StyleFormatter
from swecli.ui_textual.formatters.result_formatter import (
    RESULT_PREFIX,
    TOOL_CALL_PREFIX,
    ToolResultFormatter,
)
from swecli.ui_textual.style_tokens import GREY, PRIMARY, SUCCESS
from swecli.ui_textual.utils.tool_display import build_tool_call_text
from swecli.models.message import ToolCall

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
        # Spinner ID for progress operations (thinking spinner)
        self._progress_spinner_id: str = ""
        # Working directory for resolving relative paths
        self._working_dir = working_dir
        # Collector for nested tool calls (for session storage)
        self._pending_nested_calls: list[ToolCall] = []
        # Thinking mode visibility toggle
        self._thinking_visible = True
        # Track displayed assistant messages (for deduplication in _render_responses)
        self._displayed_assistant_messages: set[str] = set()

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

    def on_thinking(self, content: str) -> None:
        """Called when the model produces thinking content via the think tool.

        Displays thinking content in the conversation log with dark gray styling.
        Can be toggled on/off with Ctrl+Shift+T hotkey.

        Args:
            content: The reasoning/thinking text from the model
        """
        # Check visibility from chat_app (single source of truth) or fallback to local state
        if self.chat_app and hasattr(self.chat_app, '_thinking_visible'):
            if not self.chat_app._thinking_visible:
                return  # Skip display if thinking is hidden
        elif not self._thinking_visible:
            return  # Fallback to local state

        if not content or not content.strip():
            return

        # Display thinking block with special styling
        if hasattr(self.conversation, 'add_thinking_block'):
            self._run_on_ui(self.conversation.add_thinking_block, content)

    def toggle_thinking_visibility(self) -> bool:
        """Toggle thinking content visibility.

        Syncs with chat_app state if available.

        Returns:
            New visibility state (True = visible)
        """
        # Toggle app state (single source of truth) if available
        if self.chat_app and hasattr(self.chat_app, '_thinking_visible'):
            self.chat_app._thinking_visible = not self.chat_app._thinking_visible
            self._thinking_visible = self.chat_app._thinking_visible
            return self.chat_app._thinking_visible
        else:
            # Fallback to local state
            self._thinking_visible = not self._thinking_visible
            return self._thinking_visible

    def get_and_clear_nested_calls(self) -> list[ToolCall]:
        """Return collected nested calls and clear the buffer.

        Called after spawn_subagent completes to attach nested calls to the ToolCall.
        """
        calls = self._pending_nested_calls
        self._pending_nested_calls = []
        return calls

    def on_assistant_message(self, content: str) -> None:
        """Called when assistant provides a message before tool execution.

        Args:
            content: The assistant's message/thinking
        """
        if content and content.strip():
            # Track this message SYNCHRONOUSLY for deduplication (before async UI calls)
            self._displayed_assistant_messages.add(content.strip())

            # Stop spinner before showing assistant message
            # Note: Only call _stop_local_spinner which goes through SpinnerController
            # with grace period. Don't call conversation.stop_spinner directly as it
            # bypasses the grace period and removes the spinner immediately.
            if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
                self._run_on_ui(self.chat_app._stop_local_spinner)

            # Display the assistant's thinking/message
            if hasattr(self.conversation, 'add_assistant_message'):
                self._run_on_ui(self.conversation.add_assistant_message, content)

            # Record for tool summary manager
            if self.chat_app and hasattr(self.chat_app, "record_assistant_message"):
                self._run_on_ui(self.chat_app.record_assistant_message, content)

    def was_message_displayed(self, content: str) -> bool:
        """Check if a message was already displayed via on_assistant_message."""
        if not content:
            return False
        return content.strip() in self._displayed_assistant_messages

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

            display_text = Text(message, style=PRIMARY)
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

            display_text = Text(message, style=PRIMARY)
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
                result_line = Text(RESULT_PREFIX, style=GREY)
                result_line.append(message, style=GREY)
                self._run_on_ui(self.conversation.write, result_line)

    def on_interrupt(self) -> None:
        """Called when execution is interrupted by user."""
        # Stop any active progress spinners via SpinnerService
        if self._app is not None and hasattr(self._app, 'spinner_service'):
            if self._progress_spinner_id:
                self._app.spinner_service.stop(self._progress_spinner_id, success=False)
                self._progress_spinner_id = ""

        # Stop spinner
        if hasattr(self.conversation, 'stop_spinner'):
            self._run_on_ui(self.conversation.stop_spinner)
        if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
            self._run_on_ui(self.chat_app._stop_local_spinner)

        # Write the interrupt message
        from swecli.ui_textual.utils.interrupt_utils import create_interrupt_text, THINKING_INTERRUPT_MESSAGE
        interrupt_line = create_interrupt_text(THINKING_INTERRUPT_MESSAGE)
        self._run_on_ui(self.conversation.write, interrupt_line)

    def on_bash_output_line(self, line: str, is_stderr: bool = False) -> None:
        """Called for each line of bash output during execution.

        For main agent: Output is collected and shown via add_bash_output_box in on_tool_result.
        For subagents: ForwardingUICallback forwards this to parent for nested display.

        Args:
            line: A single line of output from the bash command
            is_stderr: True if this line came from stderr
        """
        # Main agent doesn't stream - output shown in on_tool_result
        pass

    def on_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_call_id: Optional[str] = None,
    ) -> None:
        """Called when a tool call is about to be executed.

        Claude Code style: Don't show anything during tool execution.
        Results appear only when the tool completes via on_tool_result.

        Args:
            tool_name: Name of the tool being called
            tool_args: Arguments for the tool call
            tool_call_id: Unique ID for this tool call (for parallel tracking)
        """
        # For think tool: stop spinner but don't display a tool call line
        # Thinking content will be shown via on_thinking callback
        if tool_name == "think":
            # Always stop the thinking spinner so thinking content appears cleanly
            # Use _stop_local_spinner to properly stop the SpinnerController
            if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
                self._run_on_ui(self.chat_app._stop_local_spinner)
            self._current_thinking = False
            return

        # Stop thinking spinner if still active
        if self._current_thinking:
            self._run_on_ui(self.conversation.stop_spinner)
            self._current_thinking = False

        if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
            self._run_on_ui(self.chat_app._stop_local_spinner)

        # Don't show tool call header here - show it in on_tool_result
        # This ensures header + result appear together even for parallel tools

    def on_tool_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        tool_call_id: Optional[str] = None,
    ) -> None:
        """Called when a tool execution completes.

        Claude Code style: Show simple result line with ⎿ prefix.
        Format: "  ⎿  Read filename (N lines)"

        Args:
            tool_name: Name of the tool that was executed
            tool_args: Arguments that were used
            result: Result of the tool execution (can be dict or string)
            tool_call_id: Unique ID for this tool call (for parallel tracking)
        """
        from rich.text import Text

        # Handle string results by converting to dict format
        if isinstance(result, str):
            result = {"success": True, "output": result}

        # Special handling for think tool - display via on_thinking callback
        if tool_name == "think" and isinstance(result, dict):
            thinking_content = result.get("_thinking_content", "")
            if thinking_content:
                self.on_thinking(thinking_content)
                # Restart spinner - model is still working on next steps
                if self.chat_app and hasattr(self.chat_app, '_start_local_spinner'):
                    self._run_on_ui(self.chat_app._start_local_spinner)
            return  # Don't show as standard tool result

        # Skip displaying interrupted operations
        if isinstance(result, dict) and result.get("interrupted"):
            return

        # Skip displaying spawn_subagent results - the command handler shows its own result
        if tool_name == "spawn_subagent":
            return

        normalized_args = self._normalize_arguments(tool_args)
        display_args = self._resolve_paths_in_args(normalized_args)

        # Bash commands: handle background vs immediate differently
        if tool_name in ("bash_execute", "run_command") and isinstance(result, dict):
            background_task_id = result.get("background_task_id")

            if background_task_id:
                # Background task - show header + simple message together (atomic)
                header_display = build_tool_call_text(tool_name, display_args)
                combined = Text()
                combined.append("\n")  # Blank line before for spacing
                combined.append(TOOL_CALL_PREFIX, style=SUCCESS)
                combined.append_text(header_display)
                combined.append("\n")
                combined.append(RESULT_PREFIX, style=GREY)
                combined.append(f"Running in background ({background_task_id})", style=GREY)
                self._run_on_ui(self.conversation.write, combined)
                # Resume spinner - LLM is processing after tool completes
                if self.chat_app and hasattr(self.chat_app, 'resume_reasoning_spinner'):
                    self._run_on_ui(self.chat_app.resume_reasoning_spinner)
                return

            is_error = not result.get("success", True)

            # Show header with leading blank line for spacing
            header_display = build_tool_call_text(tool_name, display_args)
            header_line = Text()
            header_line.append("\n")  # Blank line before for spacing
            header_line.append(TOOL_CALL_PREFIX, style=SUCCESS)
            header_line.append_text(header_display)
            self._run_on_ui(self.conversation.write, header_line)

            if hasattr(self.conversation, 'add_bash_output_box'):
                import os
                command = normalized_args.get("command", "")
                working_dir = os.getcwd()
                output = result.get("output") or result.get("stdout") or ""
                stderr = result.get("stderr") or ""
                if stderr and stderr not in output:
                    output = (output + "\n" + stderr).strip() if output else stderr
                if output in ("Command executed", "Command execution failed"):
                    output = ""

                if not is_error:
                    cmd_name = command.split()[0] if command else "command"
                    ok_line = f"OK: {cmd_name} ran successfully"
                    if output:
                        output = ok_line + "\n" + output
                    else:
                        output = ok_line

                self._run_on_ui(
                    self.conversation.add_bash_output_box,
                    output,
                    is_error,
                    command,
                    working_dir,
                    0,
                )

            # Resume spinner - LLM is processing after tool completes
            # Uses resume_reasoning_spinner which checks _is_processing flag
            if self.chat_app and hasattr(self.chat_app, 'resume_reasoning_spinner'):
                self._run_on_ui(self.chat_app.resume_reasoning_spinner)
            return

        # Build combined header + result as single Text (atomic write for parallel tools)
        # Include leading newline for spacing between sections
        success = result.get("success", True) if isinstance(result, dict) else True

        # Build header line with leading blank line for spacing
        header_display = build_tool_call_text(tool_name, display_args)
        combined = Text()
        combined.append("\n")  # Blank line before for spacing
        combined.append(TOOL_CALL_PREFIX, style=SUCCESS)
        combined.append_text(header_display)
        combined.append("\n")

        if not success:
            # Failed tool: show header + error result
            error_msg = result.get("error", "") or result.get("message", "") or "Error"
            if isinstance(error_msg, str) and len(error_msg) > 100:
                error_msg = error_msg[:97] + "..."
            combined.append(RESULT_PREFIX, style=GREY)
            combined.append(error_msg, style=GREY)
            self._run_on_ui(self.conversation.write, combined)

            # Resume spinner - LLM is processing after tool completes
            if self.chat_app and hasattr(self.chat_app, 'resume_reasoning_spinner'):
                self._run_on_ui(self.chat_app.resume_reasoning_spinner)
        else:
            # Successful tool: show header + result
            result_text = self._format_simple_result(tool_name, normalized_args, result)
            combined.append(RESULT_PREFIX, style=GREY)
            combined.append(result_text, style=GREY)
            self._run_on_ui(self.conversation.write, combined)

            # Handle diff lines for edit_file (show after summary)
            if tool_name == "edit_file" and isinstance(result, dict):
                formatted = self.formatter.format_tool_result(tool_name, normalized_args, result)
                if isinstance(formatted, str):
                    collected_lines = []
                    for line in formatted.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("⎿"):
                            text = stripped.lstrip("⎿").strip()
                            if text and not text.startswith("@@") and "Updated" not in text:
                                collected_lines.append(text)
                    if collected_lines:
                        self._run_on_ui(self.conversation.add_tool_result_continuation, collected_lines)

            if self.chat_app and hasattr(self.chat_app, "record_tool_summary"):
                self._run_on_ui(self.chat_app.record_tool_summary, tool_name, normalized_args, [result_text])

        # Restart spinner - LLM is still processing after tool completes
        if self.chat_app and hasattr(self.chat_app, '_start_local_spinner'):
            self._run_on_ui(self.chat_app._start_local_spinner)

        # Auto-refresh todo panel after todo tool execution
        if tool_name in {"write_todos", "update_todo", "complete_todo"}:
            self._refresh_todo_panel()

    def _format_simple_result(self, tool_name: str, tool_args: Dict[str, Any], result: Any) -> str:
        """Format tool result in Claude Code style (simple, one line).

        Args:
            tool_name: Name of the tool
            tool_args: Tool arguments
            result: Tool result

        Returns:
            Simple one-line result string like "Read filename (N lines)"
        """
        if tool_name == "read_file":
            path = tool_args.get("file_path", "")
            filename = Path(path).name if path else "file"
            # Calculate lines from output content
            output = result.get("output", "") if isinstance(result, dict) else ""
            lines = output.count("\n") + 1 if output else 0
            return f"Read {filename} ({lines} lines)"

        elif tool_name == "edit_file":
            path = tool_args.get("file_path", "")
            filename = Path(path).name if path else "file"
            if isinstance(result, dict):
                added = result.get("lines_added", 0) or 0
                removed = result.get("lines_removed", 0) or 0
                add_str = f"{added} addition" if added == 1 else f"{added} additions"
                rem_str = f"{removed} removal" if removed == 1 else f"{removed} removals"
                return f"Updated {filename} with {add_str} and {rem_str}"
            return f"Updated {filename}"

        elif tool_name == "write_file":
            path = tool_args.get("file_path", "")
            filename = Path(path).name if path else "file"
            return f"Wrote {filename}"

        elif tool_name == "list_files":
            path = tool_args.get("path", ".")
            dirname = Path(path).name if path else "."
            count = 0
            if isinstance(result, dict):
                files = result.get("files", [])
                count = len(files) if isinstance(files, list) else 0
            return f"Listed {count} files in {dirname}"

        elif tool_name == "search":
            pattern = tool_args.get("pattern", "")
            count = 0
            if isinstance(result, dict):
                matches = result.get("matches", [])
                count = len(matches) if isinstance(matches, list) else 0
            return f"Found {count} matches for '{pattern}'"

        elif tool_name == "fetch_url":
            url = tool_args.get("url", "")
            # Truncate long URLs
            if len(url) > 50:
                url = url[:47] + "..."
            return f"Fetched {url}"

        elif tool_name in ("bash_execute", "run_command"):
            command = tool_args.get("command", "")
            cmd_name = command.split()[0] if command else "command"
            success = result.get("success", True) if isinstance(result, dict) else True
            if success:
                return f"Ran {cmd_name}"
            return f"Failed: {cmd_name}"

        else:
            # Generic format for unknown tools
            success = result.get("success", True) if isinstance(result, dict) else True
            if success:
                return f"{tool_name} completed"
            return f"{tool_name} failed"

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

        # Update the nested tool call status to complete (for ALL tools including bash)
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
                # Signature: (output, is_error, command, working_dir, depth)
                self._run_on_ui(
                    self.conversation.add_nested_bash_output_box,
                    output,
                    is_error,
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

        # Collect for session storage
        self._pending_nested_calls.append(ToolCall(
            id=f"nested_{len(self._pending_nested_calls)}",
            name=tool_name,
            parameters=tool_args,
            result=result,
        ))

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

        # Debug logging for missing content
        if not lines:
            import logging
            logging.getLogger(__name__).debug(
                f"No display lines for nested {tool_name}: result keys={list(result.keys()) if isinstance(result, dict) else 'not dict'}"
            )

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
        """Execute a function on the Textual UI thread and WAIT for completion.

        Uses call_from_thread to ensure ordered execution of UI updates.
        This prevents race conditions where messages are displayed out of order.
        """
        if self._app is not None:
            self._app.call_from_thread(func, *args, **kwargs)
        else:
            func(*args, **kwargs)

    def _run_on_ui_non_blocking(self, func, *args, **kwargs) -> None:
        """Execute a function on the Textual UI thread WITHOUT waiting.

        Uses call_soon_threadsafe to schedule work on the event loop
        without blocking the calling thread. Use with caution as this
        does not guarantee execution order.
        """
        if self._app is not None:
            loop = getattr(self._app, '_loop', None)
            if loop is not None:
                loop.call_soon_threadsafe(lambda: func(*args, **kwargs))
            else:
                self._app.call_from_thread(func, *args, **kwargs)
        else:
            func(*args, **kwargs)

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
