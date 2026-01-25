"""UI callback for real-time tool call display in Textual UI."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from swecli.ui_textual.formatters.style_formatter import StyleFormatter
from swecli.ui_textual.style_tokens import GREY, PRIMARY
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
        # Spinner IDs for tracking active spinners via SpinnerService
        self._progress_spinner_id: str = ""
        # Dict to track multiple tool spinners for parallel execution
        # Maps tool_call_id -> spinner_id
        self._tool_spinner_ids: Dict[str, str] = {}
        # Working directory for resolving relative paths
        self._working_dir = working_dir
        # Collector for nested tool calls (for session storage)
        self._pending_nested_calls: list[ToolCall] = []
        # Thinking mode visibility toggle (default OFF)
        self._thinking_visible = False
        # Track parallel agent group state SYNCHRONOUSLY to avoid race conditions
        # This is set immediately when parallel agents start, before async UI update
        self._in_parallel_agent_group: bool = False
        # Track current single agent ID for completion callback
        self._current_single_agent_id: str | None = None

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
        if self.chat_app and hasattr(self.chat_app, "_thinking_visible"):
            if not self.chat_app._thinking_visible:
                return  # Skip display if thinking is hidden
        elif not self._thinking_visible:
            return  # Fallback to local state

        if not content or not content.strip():
            return

        # Stop spinner BEFORE displaying thinking trace (so it appears above, not below)
        if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
            self._run_on_ui(self.chat_app._stop_local_spinner)

        # Display thinking block with special styling
        if hasattr(self.conversation, "add_thinking_block"):
            self._run_on_ui(self.conversation.add_thinking_block, content)

        # Restart spinner for the action phase
        if self.chat_app and hasattr(self.chat_app, "_start_local_spinner"):
            self._run_on_ui(self.chat_app._start_local_spinner)

    def toggle_thinking_visibility(self) -> bool:
        """Toggle thinking content visibility.

        Syncs with chat_app state if available.

        Returns:
            New visibility state (True = visible)
        """
        # Toggle app state (single source of truth) if available
        if self.chat_app and hasattr(self.chat_app, "_thinking_visible"):
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
            # Stop spinner before showing assistant message
            # Note: Only call _stop_local_spinner which goes through SpinnerController
            # with grace period. Don't call conversation.stop_spinner directly as it
            # bypasses the grace period and removes the spinner immediately.
            if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
                self._run_on_ui(self.chat_app._stop_local_spinner)

            # Display the assistant's thinking/message
            if hasattr(self.conversation, "add_assistant_message"):
                self._run_on_ui(self.conversation.add_assistant_message, content)
                # Force refresh to ensure immediate visual update
                if hasattr(self.conversation, "refresh"):
                    self._run_on_ui(self.conversation.refresh)

    def on_message(self, message: str) -> None:
        """Called to display a simple progress message (no spinner).

        Args:
            message: The message to display
        """
        if hasattr(self.conversation, "add_system_message"):
            self._run_on_ui(self.conversation.add_system_message, message)

    def on_progress_start(self, message: str) -> None:
        """Called when a progress operation starts (shows spinner).

        Args:
            message: The progress message to display with spinner
        """
        # Use SpinnerService for unified spinner management
        if self._app is not None and hasattr(self._app, "spinner_service"):
            self._progress_spinner_id = self._app.spinner_service.start(message)
        else:
            # Fallback to direct calls if SpinnerService not available
            from rich.text import Text

            display_text = Text(message, style=PRIMARY)
            if hasattr(self.conversation, "add_tool_call") and self._app is not None:
                self._app.call_from_thread(self.conversation.add_tool_call, display_text)
            if hasattr(self.conversation, "start_tool_execution") and self._app is not None:
                self._app.call_from_thread(self.conversation.start_tool_execution)

    def on_progress_update(self, message: str) -> None:
        """Update progress text in-place (same line, keeps spinner running).

        Use this for multi-step progress where you want to update the text
        without creating a new line. The spinner and timer continue running.

        Args:
            message: New progress message to display
        """
        # Use SpinnerService for unified spinner management
        if (
            self._progress_spinner_id
            and self._app is not None
            and hasattr(self._app, "spinner_service")
        ):
            self._app.spinner_service.update(self._progress_spinner_id, message)
        else:
            # Fallback to direct calls if SpinnerService not available
            from rich.text import Text

            display_text = Text(message, style=PRIMARY)
            if hasattr(self.conversation, "update_progress_text"):
                self._run_on_ui(self.conversation.update_progress_text, display_text)

    def on_progress_complete(self, message: str = "", success: bool = True) -> None:
        """Called when a progress operation completes.

        Args:
            message: Optional result message to display
            success: Whether the operation succeeded (affects bullet color)
        """
        # Use SpinnerService for unified spinner management
        if (
            self._progress_spinner_id
            and self._app is not None
            and hasattr(self._app, "spinner_service")
        ):
            self._app.spinner_service.stop(self._progress_spinner_id, success, message)
            self._progress_spinner_id = ""
        else:
            # Fallback to direct calls if SpinnerService not available
            from rich.text import Text

            # Stop spinner (shows green/red bullet based on success)
            if hasattr(self.conversation, "stop_tool_execution"):
                self._run_on_ui(lambda: self.conversation.stop_tool_execution(success))

            # Show result line (if message provided)
            if message:
                result_line = Text("  ⎿  ", style=GREY)
                result_line.append(message, style=GREY)
                self._run_on_ui(self.conversation.write, result_line)

    def on_interrupt(self) -> None:
        """Called when execution is interrupted by user.

        Displays the interrupt message directly by replacing the blank line after user prompt.
        """
        # Stop any active spinners via SpinnerService
        if self._app is not None and hasattr(self._app, "spinner_service"):
            if self._tool_spinner_id:
                self._app.spinner_service.stop(self._tool_spinner_id, success=False)
                self._tool_spinner_id = ""
            if self._progress_spinner_id:
                self._app.spinner_service.stop(self._progress_spinner_id, success=False)
                self._progress_spinner_id = ""

        # Stop spinner first - this removes spinner lines but leaves the blank line after user prompt
        if hasattr(self.conversation, "stop_spinner"):
            self._run_on_ui(self.conversation.stop_spinner)
        if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
            self._run_on_ui(self.chat_app._stop_local_spinner)

        # The key insight: after user message, there's a blank line (added by add_user_message)
        # After stopping spinner, this blank line is the last line
        # We need to remove it using _truncate_from to properly update widget state
        def write_interrupt_replacing_blank_line():

            # Check if we have lines and last line is blank
            if hasattr(self.conversation, "lines") and len(self.conversation.lines) > 0:
                # Check if last line is blank
                last_line = self.conversation.lines[-1]

                # RichLog stores lines as Strip objects, not Text objects
                # A blank line is a Strip with empty segments or a single empty Segment
                is_blank = False

                # Check if it's a Strip object with empty content
                if hasattr(last_line, "_segments"):
                    segments = last_line._segments
                    if len(segments) == 0:
                        is_blank = True
                    elif len(segments) == 1 and segments[0].text == "":
                        is_blank = True
                elif hasattr(last_line, "plain"):
                    # Fallback for Text objects
                    if last_line.plain.strip() == "":
                        is_blank = True

                if is_blank:
                    # Use _truncate_from to properly remove the blank line and update widget state
                    if hasattr(self.conversation, "_truncate_from"):
                        self.conversation._truncate_from(len(self.conversation.lines) - 1)

            # Now write the interrupt message using shared utility
            from swecli.ui_textual.utils.interrupt_utils import (
                create_interrupt_text,
                THINKING_INTERRUPT_MESSAGE,
            )

            interrupt_line = create_interrupt_text(THINKING_INTERRUPT_MESSAGE)
            self.conversation.write(interrupt_line)

        self._run_on_ui(write_interrupt_replacing_blank_line)

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

        # Skip displaying individual spawn_subagent calls when in parallel mode
        # The parallel group header handles display for these
        if tool_name == "spawn_subagent" and self._in_parallel_agent_group:
            return  # Already displayed in parallel header, skip regular display

        # For single spawn_subagent calls, use single agent display
        # The tool still needs to execute - we just want custom display
        if tool_name == "spawn_subagent" and not self._in_parallel_agent_group:
            # Normalize args first - tool_args may be a JSON string from react_executor
            normalized = self._normalize_arguments(tool_args)
            subagent_type = normalized.get("subagent_type", "general-purpose")
            description = normalized.get("description", "")

            # Set the flag to prevent nested tool calls from showing individually
            self._in_parallel_agent_group = True

            # Use tool_call_id if available, otherwise use the agent type as the key
            agent_key = tool_call_id or subagent_type
            self._current_single_agent_id = agent_key  # Store for completion

            # Stop thinking spinner if still active (shows "Plotting...", etc.)
            if self._current_thinking:
                self._run_on_ui(self.conversation.stop_spinner)
                self._current_thinking = False

            # Stop any local spinner
            if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
                self._run_on_ui(self.chat_app._stop_local_spinner)

            # Call on_single_agent_start for proper single agent display
            self.on_single_agent_start(subagent_type, description, agent_key)
            return  # Prevent SpinnerService from creating competing display

        # Stop thinking spinner if still active
        if self._current_thinking:
            self._run_on_ui(self.conversation.stop_spinner)
            self._current_thinking = False

        if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
            self._run_on_ui(self.chat_app._stop_local_spinner)

        # Skip regular display for spawn_subagent - parallel display handles it
        if tool_name != "spawn_subagent":
            normalized_args = self._normalize_arguments(tool_args)
            # Resolve relative paths to absolute for display
            display_args = self._resolve_paths_in_args(normalized_args)
            display_text = build_tool_call_text(tool_name, display_args)

            # Use SpinnerService for unified spinner management
            if self._app is not None and hasattr(self._app, "spinner_service"):
                # Bash commands don't need placeholders - their output is rendered separately
                is_bash = tool_name in ("bash_execute", "run_command")
                spinner_id = self._app.spinner_service.start(display_text, skip_placeholder=is_bash)
                # Track spinner by tool_call_id for parallel execution
                key = tool_call_id or f"_default_{id(tool_args)}"
                self._tool_spinner_ids[key] = spinner_id
            else:
                # Fallback to direct calls if SpinnerService not available
                if hasattr(self.conversation, "add_tool_call") and self._app is not None:
                    self._app.call_from_thread(self.conversation.add_tool_call, display_text)
                if hasattr(self.conversation, "start_tool_execution") and self._app is not None:
                    self._app.call_from_thread(self.conversation.start_tool_execution)

    def on_tool_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        tool_call_id: Optional[str] = None,
    ) -> None:
        """Called when a tool execution completes.

        Args:
            tool_name: Name of the tool that was executed
            tool_args: Arguments that were used
            result: Result of the tool execution (can be dict or string)
            tool_call_id: Unique ID for this tool call (for parallel tracking)
        """
        # Handle string results by converting to dict format
        if isinstance(result, str):
            result = {"success": True, "output": result}

        # Special handling for think tool - display via on_thinking callback
        # Check BEFORE spinner handling since we didn't start a spinner for think
        if tool_name == "think" and isinstance(result, dict):
            thinking_content = result.get("_thinking_content", "")
            if thinking_content:
                self.on_thinking(thinking_content)

            # Restart spinner - model continues processing after think
            if self.chat_app and hasattr(self.chat_app, "_start_local_spinner"):
                self._run_on_ui(self.chat_app._start_local_spinner)
            return  # Don't show as standard tool result

        # Stop spinner animation
        # Pass success status to color the bullet (green for success, red for failure)
        success = result.get("success", True) if isinstance(result, dict) else True

        # Look up spinner_id by tool_call_id for parallel execution
        key = tool_call_id or f"_default_{id(tool_args)}"
        spinner_id = self._tool_spinner_ids.pop(key, None)

        # Special handling for ask_user tool - the result placeholder gets removed when
        # the ask_user panel is displayed (render_ask_user_prompt removes trailing blank lines).
        # So we need to add the result line directly instead of relying on spinner_service.stop()
        if tool_name == "ask_user" and isinstance(result, dict):
            # Stop spinner without result message (placeholder was removed)
            if spinner_id and self._app is not None and hasattr(self._app, "spinner_service"):
                self._app.spinner_service.stop(spinner_id, success, "")

            # Add result line directly with standard ⎿ prefix (2 spaces, matching spinner_service)
            output = result.get("output", "")
            if output and self._app is not None:
                from rich.text import Text
                from swecli.ui_textual.style_tokens import GREY

                result_line = Text("  ⎿  ", style=GREY)
                result_line.append(output, style=GREY)
                self._run_on_ui(self.conversation.write, result_line)
            return

        # Skip displaying interrupted operations
        # These are already shown by the approval controller interrupt message
        if isinstance(result, dict) and result.get("interrupted"):
            # Still stop the spinner
            if spinner_id and self._app is not None and hasattr(self._app, "spinner_service"):
                self._app.spinner_service.stop(spinner_id, False, "Interrupted")
            return

        # Skip displaying spawn_subagent results - the command handler shows its own result
        # EXCEPT for ask-user which needs to show the answer summary
        if tool_name == "spawn_subagent":
            normalized_args = self._normalize_arguments(tool_args)
            subagent_type = normalized_args.get("subagent_type", "")

            if spinner_id and self._app is not None and hasattr(self._app, "spinner_service"):
                self._app.spinner_service.stop(spinner_id, success)

            # For single agent spawns, mark as complete
            if self._in_parallel_agent_group:
                agent_key = getattr(self, "_current_single_agent_id", None)
                if agent_key:
                    self.on_single_agent_complete(agent_key, success)
                self._in_parallel_agent_group = False
                self._current_single_agent_id = None

            # For ask-user, show the result summary with ⎿ prefix
            # This is done AFTER completion to add the result line below the header
            if subagent_type == "ask-user" and isinstance(result, dict):
                content = result.get("content", "")
                if content and self._app is not None:
                    # Add result line with ⎿ prefix
                    self._run_on_ui(
                        self.conversation.add_tool_result,
                        content,
                    )

            return

        # Bash commands: handle background vs immediate differently
        if tool_name in ("bash_execute", "run_command") and isinstance(result, dict):
            background_task_id = result.get("background_task_id")

            if background_task_id:
                # Background task - show special message (Claude Code style)
                if spinner_id and self._app is not None and hasattr(self._app, "spinner_service"):
                    self._app.spinner_service.stop(
                        spinner_id, success, f"Running in background ({background_task_id})"
                    )
                return

            # Quick command - stop spinner first, then show bash output box
            if spinner_id and self._app is not None and hasattr(self._app, "spinner_service"):
                self._app.spinner_service.stop(spinner_id, success, "")

            is_error = not result.get("success", True)

            if hasattr(self.conversation, "add_bash_output_box"):
                import os

                command = self._normalize_arguments(tool_args).get("command", "")
                working_dir = os.getcwd()
                # Use "output" key (combined stdout+stderr from process_handlers),
                # falling back to "stdout" for compatibility
                output = result.get("output") or result.get("stdout") or ""
                stderr = result.get("stderr") or ""
                # Combine stdout and stderr for display
                if stderr and stderr not in output:
                    output = (output + "\n" + stderr).strip() if output else stderr
                # Filter out placeholder messages
                if output in ("Command executed", "Command execution failed"):
                    output = ""

                # Add OK prefix for successful commands (Claude Code style)
                if not is_error:
                    # Extract command name for the OK message
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
                    0,  # depth
                )

            return

        # Format the result using the Claude-style formatter
        normalized_args = self._normalize_arguments(tool_args)
        formatted = self.formatter.format_tool_result(tool_name, normalized_args, result)

        # Extract the result line(s) from the formatted output
        # First ⎿ line goes to spinner result placeholder, additional lines displayed separately
        summary_lines: list[str] = []
        collected_lines: list[str] = []
        if isinstance(formatted, str):
            lines = formatted.splitlines()
            first_result_line_seen = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("⎿"):
                    result_text = stripped.lstrip("⎿").strip()
                    if result_text:
                        if not first_result_line_seen:
                            # First ⎿ line goes to placeholder only
                            first_result_line_seen = True
                            summary_lines.append(result_text)
                        else:
                            # Subsequent ⎿ lines go to collected_lines (e.g., diff content)
                            # Skip @@ header lines
                            if not result_text.startswith("@@"):
                                collected_lines.append(result_text)
        else:
            self._run_on_ui(self.conversation.write, formatted)
            if hasattr(formatted, "renderable") and hasattr(formatted, "title"):
                # Panels typically summarize tool output in title/body; try to capture text
                renderable = getattr(formatted, "renderable", None)
                if isinstance(renderable, str):
                    summary_lines.append(renderable.strip())

        # Stop spinner WITH the first summary line (for parallel tool display)
        first_summary = summary_lines[0] if summary_lines else ""
        if spinner_id and self._app is not None and hasattr(self._app, "spinner_service"):
            self._app.spinner_service.stop(spinner_id, success, first_summary)
        else:
            # Fallback to direct calls if SpinnerService not available
            if hasattr(self.conversation, "stop_tool_execution"):
                self._run_on_ui(lambda: self.conversation.stop_tool_execution(success))

        # Write tool result continuation (e.g., diff lines for edit_file)
        # These follow the summary line, so no ⎿ prefix needed - just space indentation
        if collected_lines:
            self._run_on_ui(self.conversation.add_tool_result_continuation, collected_lines)

        if summary_lines and self.chat_app and hasattr(self.chat_app, "record_tool_summary"):
            self._run_on_ui(
                self.chat_app.record_tool_summary, tool_name, normalized_args, summary_lines.copy()
            )

        # Auto-refresh todo panel after todo tool execution
        if tool_name in {"write_todos", "update_todo", "complete_todo"}:
            self._refresh_todo_panel()

    def on_nested_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        depth: int,
        parent: str,
        tool_id: str = "",
    ) -> None:
        """Called when a nested tool call (from subagent) is about to be executed.

        Args:
            tool_name: Name of the tool being called
            tool_args: Arguments for the tool call
            depth: Nesting depth level (1 = direct child of main agent)
            parent: Name/identifier of the parent subagent
            tool_id: Unique tool call ID for tracking parallel tools
        """
        normalized_args = self._normalize_arguments(tool_args)

        # Display nested tool call with indentation (BLOCKING to ensure timer starts before tool executes)
        if hasattr(self.conversation, "add_nested_tool_call") and self._app is not None:
            display_text = build_tool_call_text(tool_name, normalized_args)
            self._app.call_from_thread(
                self.conversation.add_nested_tool_call,
                display_text,
                depth,
                parent,
                tool_id,
            )

    def on_nested_tool_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        depth: int,
        parent: str,
        tool_id: str = "",
    ) -> None:
        """Called when a nested tool execution (from subagent) completes.

        Args:
            tool_name: Name of the tool that was executed
            tool_args: Arguments that were used
            result: Result of the tool execution (can be dict or string)
            depth: Nesting depth level
            parent: Name/identifier of the parent subagent
            tool_id: Unique tool call ID for tracking parallel tools
        """
        # Handle string results by converting to dict format
        if isinstance(result, str):
            result = {"success": True, "output": result}

        # Collect for session storage (always, even in collapsed mode)
        self._pending_nested_calls.append(
            ToolCall(
                id=f"nested_{len(self._pending_nested_calls)}",
                name=tool_name,
                parameters=tool_args,
                result=result,
            )
        )

        # Skip ALL display when in collapsed parallel mode
        # The header shows aggregated stats, individual tool results are hidden
        if self._in_parallel_agent_group:
            return

        # Skip displaying interrupted operations
        # These are already shown by the approval controller interrupt message
        if isinstance(result, dict) and result.get("interrupted"):
            # Still update the tool call status to show it was interrupted
            # Use BLOCKING call_from_thread to ensure display updates before next tool
            if hasattr(self.conversation, "complete_nested_tool_call") and self._app is not None:
                self._app.call_from_thread(
                    self.conversation.complete_nested_tool_call,
                    tool_name,
                    depth,
                    parent,
                    False,  # success=False for interrupted
                    tool_id,
                )
            return

        # Update the nested tool call status to complete (for ALL tools including bash)
        # Use BLOCKING call_from_thread to ensure each tool's completion is displayed
        # before the next tool starts (fixes "all at once" display issue)
        if hasattr(self.conversation, "complete_nested_tool_call") and self._app is not None:
            success = result.get("success", False) if isinstance(result, dict) else True
            self._app.call_from_thread(
                self.conversation.complete_nested_tool_call,
                tool_name,
                depth,
                parent,
                success,
                tool_id,
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

            if hasattr(self.conversation, "add_nested_bash_output_box"):
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
            if diff_text and hasattr(self.conversation, "add_edit_diff_result"):
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
        if lines and hasattr(self.conversation, "add_nested_tool_sub_results"):
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

        if items and hasattr(self.conversation, "add_todo_sub_results"):
            self._run_on_ui(self.conversation.add_todo_sub_results, items, depth)

    def _display_todo_update_result(
        self, args: Dict[str, Any], todo_data: Dict[str, Any], depth: int
    ) -> None:
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

        if hasattr(self.conversation, "add_todo_sub_result"):
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

        if hasattr(self.conversation, "add_todo_sub_result"):
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
            loop = getattr(self._app, "_loop", None)
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
        if self.chat_app and hasattr(self.chat_app, "runner"):
            runner = self.chat_app.runner
            if hasattr(runner, "query_processor"):
                query_processor = runner.query_processor
                if hasattr(query_processor, "task_monitor"):
                    task_monitor = query_processor.task_monitor
                    if task_monitor and hasattr(task_monitor, "should_interrupt"):
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
        if hasattr(self.conversation, "add_debug_message"):
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

    # --- Parallel Agent Group Methods ---

    def on_parallel_agents_start(self, agent_infos: list[dict]) -> None:
        """Called when parallel agents start executing.

        Args:
            agent_infos: List of agent info dicts with keys:
                - agent_type: Type of agent (e.g., "Explore")
                - description: Short description of agent's task
                - tool_call_id: Unique ID for tracking this agent
        """
        print(f"[DEBUG] on_parallel_agents_start: {agent_infos}", file=sys.stderr)

        # Stop thinking spinner if still active (shows "Plotting...", etc.)
        if self._current_thinking:
            self._run_on_ui(self.conversation.stop_spinner)
            self._current_thinking = False

        # Stop any local spinner
        if self.chat_app and hasattr(self.chat_app, "_stop_local_spinner"):
            self._run_on_ui(self.chat_app._stop_local_spinner)

        # Set flag SYNCHRONOUSLY before async UI update to prevent race conditions
        # This ensures on_tool_call sees the flag immediately
        self._in_parallel_agent_group = True

        if hasattr(self.conversation, "on_parallel_agents_start") and self._app is not None:
            print("[DEBUG] Calling conversation.on_parallel_agents_start", file=sys.stderr)
            self._app.call_from_thread(
                self.conversation.on_parallel_agents_start,
                agent_infos,
            )
        else:
            print(
                f"[DEBUG] Missing on_parallel_agents_start or app: has_method={hasattr(self.conversation, 'on_parallel_agents_start')}, _app={self._app}",
                file=sys.stderr,
            )

    def on_parallel_agent_complete(self, tool_call_id: str, success: bool) -> None:
        """Called when a parallel agent completes.

        Args:
            tool_call_id: Unique tool call ID of the agent that completed
            success: Whether the agent succeeded
        """
        if hasattr(self.conversation, "on_parallel_agent_complete") and self._app is not None:
            self._app.call_from_thread(
                self.conversation.on_parallel_agent_complete,
                tool_call_id,
                success,
            )

    def on_parallel_agents_done(self) -> None:
        """Called when all parallel agents have completed."""
        # Clear flag SYNCHRONOUSLY to allow normal tool call display to resume
        self._in_parallel_agent_group = False

        if hasattr(self.conversation, "on_parallel_agents_done") and self._app is not None:
            self._app.call_from_thread(self.conversation.on_parallel_agents_done)

    def on_single_agent_start(self, agent_type: str, description: str, tool_call_id: str) -> None:
        """Called when a single subagent starts.

        Args:
            agent_type: Type of agent (e.g., "Explore", "Code-Explorer")
            description: Task description
            tool_call_id: Unique ID for tracking
        """
        if hasattr(self.conversation, "on_single_agent_start") and self._app is not None:
            self._app.call_from_thread(
                self.conversation.on_single_agent_start,
                agent_type,
                description,
                tool_call_id,
            )

    def on_single_agent_complete(self, tool_call_id: str, success: bool = True) -> None:
        """Called when a single subagent completes.

        Args:
            tool_call_id: Unique ID of the agent that completed
            success: Whether the agent succeeded
        """
        if hasattr(self.conversation, "on_single_agent_complete") and self._app is not None:
            self._app.call_from_thread(
                self.conversation.on_single_agent_complete,
                tool_call_id,
                success,
            )

    def toggle_parallel_expansion(self) -> bool:
        """Toggle the expand/collapse state of parallel agent display.

        Returns:
            New expansion state (True = expanded)
        """
        if hasattr(self.conversation, "toggle_parallel_expansion"):
            return self.conversation.toggle_parallel_expansion()
        return True

    def has_active_parallel_group(self) -> bool:
        """Check if there's an active parallel agent group.

        Returns:
            True if a parallel group is currently active
        """
        if hasattr(self.conversation, "has_active_parallel_group"):
            return self.conversation.has_active_parallel_group()
        return False
