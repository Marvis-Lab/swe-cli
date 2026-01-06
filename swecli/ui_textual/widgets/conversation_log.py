"""Conversation log widget with markdown-aware rendering and tool formatting."""

from __future__ import annotations

import re
import threading
import time
from typing import Any, List, Tuple

from rich.console import Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.events import MouseDown, MouseMove, MouseScrollDown, MouseScrollUp, MouseUp
from textual.geometry import Size
from textual.timer import Timer
from textual.widgets import RichLog

from swecli.ui_textual.renderers import render_markdown_text_segment
from swecli.ui_textual.constants import TOOL_ERROR_SENTINEL
from swecli.ui_textual.style_tokens import ERROR, GREY
from swecli.ui_textual.widgets.terminal_box_renderer import (
    TerminalBoxConfig,
)
from swecli.ui_textual.widgets.conversation.spinner_manager import DefaultSpinnerManager
from swecli.ui_textual.widgets.conversation.message_renderer import DefaultMessageRenderer
from swecli.ui_textual.widgets.conversation.tool_renderer import DefaultToolRenderer


class ConversationLog(RichLog):
    """Enhanced RichLog for conversation display with scrolling support."""

    can_focus = True
    ALLOW_SELECT = True

    def __init__(self, **kwargs):
        super().__init__(
            **kwargs,
            wrap=True,
            highlight=True,
            markup=True,
            auto_scroll=True,
            max_lines=10000,
        )
        self._user_scrolled = False
        self._user_scrolled = False
        self._last_assistant_rendered: str | None = None
        self._spinner_manager = DefaultSpinnerManager(self, None)
        self._message_renderer = DefaultMessageRenderer(self, None)
        self._tool_renderer = DefaultToolRenderer(self, None)
        # self._tool_display: Text | None = None  # Moved to ToolRenderer
        # self._tool_spinner_timer: Timer | None = None # Moved
        self._spinner_active = False # Still used for main spinner? Checked usage.
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        
        self._nested_spinner_char = "⏺"  # Single character for nested/subagent tools
        # Ultra-smooth color gradient: 24 steps for slow breathing effect
        self._nested_color_gradient = [
            "#00ff00",  # Peak bright
            "#00f500", "#00eb00", "#00e100", "#00d700", "#00cd00",
            "#00c300", "#00b900", "#00af00", "#00a500", "#009b00",
            "#009100",  # Dimmest
            "#009b00", "#00a500", "#00af00", "#00b900", "#00c300",
            "#00cd00", "#00d700", "#00e100", "#00eb00", "#00f500",
            "#00ff00",  # Back to peak
        ]
        self._nested_color_index = 0
        self._spinner_index = 0
        self._tool_call_start: int | None = None
        self._approval_start: int | None = None
        self._tool_timer_start: float | None = None
        self._tool_last_elapsed: int | None = None
        self._debug_enabled = False  # Enable debug messages by default
        self._protected_lines: set[int] = set()  # Lines that should not be truncated
        self.MAX_PROTECTED_LINES = 200
        # Nested tool call pulsing animation state
        self._nested_tool_line: int | None = None  # Line index of last nested tool call
        self._nested_tool_text: Text | None = None  # Original text for the nested tool
        self._nested_tool_depth: int = 1  # Depth for indentation
        self._nested_pulse_bright = True  # Toggle for dim/bright pulsing
        self._nested_pulse_counter = 0  # Counter to slow down pulse rate
        self._nested_tool_timer: Timer | None = None  # Independent timer for nested tool animation
        self._nested_tool_timer_start: float | None = None  # Start time for elapsed tracking
        # Track if last written line has content (for blank line insertion logic)
        self._last_line_has_content = False
        # Streaming bash box state
        self._streaming_box_header_line: int | None = None  # Line index of header row
        self._streaming_box_width: int = 60  # Box width
        self._streaming_box_top_line: int | None = None  # Line index of top border (for error restyling)
        # Streaming box data storage (for rebuild on close)
        self._streaming_box_command: str = ""
        self._streaming_box_working_dir: str = "."
        self._streaming_box_content_lines: list[tuple[str, bool]] = []  # (line, is_stderr)
        self._streaming_box_config: TerminalBoxConfig | None = None  # Config for streaming box
        # Mouse drag detection for selection tip
        self._mouse_down_pos: tuple[int, int] | None = None
        # Thinking spinner animation state (widget-level timer for reliable animation)
        self._thinking_spinner_timer: Timer | None = None
        self._thinking_spinner_active: bool = False
        self._thinking_spinner_index: int = 0
        self._thinking_message: str = ""
        self._thinking_tip: str = ""
        self._thinking_started_at: float = 0.0
        self._pending_stop_timer: Timer | None = None  # Delayed stop for minimum visibility
        # Python threading.Timer as fallback (bypasses Textual's event loop)
        self._thinking_thread_timer: threading.Timer | None = None
        # Thread timers for tool spinners (bypass blocked event loop during tool execution)
        self._tool_thread_timer: threading.Timer | None = None
        self._nested_tool_thread_timer: threading.Timer | None = None

    def call_from_thread(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        """Forward call_from_thread to the app."""
        if self.app:
            self.app.call_from_thread(callback, *args, **kwargs)

    def refresh_line(self, y: int) -> None:
        """Refresh a specific line by invalidating cache and repainting."""
        # Aggressively clear cache to ensure spinner animation updates
        if hasattr(self, '_line_cache'):
            self._line_cache.clear()
        self.refresh()

    def write(self, content, *args, **kwargs) -> None:
        """Override write to track content state for spacing logic."""
        super().write(content, *args, **kwargs)
        # Track if this was a blank line or content
        if isinstance(content, Text):
            self._last_line_has_content = bool(content.plain.strip())
        else:
            self._last_line_has_content = bool(str(content).strip())

    def on_mount(self) -> None:
        if self.app:
            self._spinner_manager.app = self.app
            self._message_renderer.app = self.app
            self._tool_renderer.app = self.app
        return

    def on_unmount(self) -> None:
        self._tool_renderer.cleanup()
        self._spinner_manager.cleanup()
        
        if self._thinking_thread_timer is not None:
            self._thinking_thread_timer.cancel()
            self._thinking_thread_timer = None

    def set_debug_enabled(self, enabled: bool) -> None:
        """Enable or disable debug message display."""
        self._debug_enabled = enabled

    def add_debug_message(self, message: str, prefix: str = "DEBUG") -> None:
        """Add a debug message with gray/dimmed styling for execution flow visibility.

        Args:
            message: The debug message to display
            prefix: Optional prefix for categorizing debug messages (e.g., "QUERY", "TOOL", "AGENT")
        """
        if not self._debug_enabled:
            return
        debug_text = Text()
        debug_text.append(f"  [{prefix}] ", style="dim cyan")
        debug_text.append(message, style="dim")
        self.write(debug_text)

        # Mark this line as protected from truncation
        line_idx = len(self.lines) - 1
        self._protected_lines.add(line_idx)

        # Prune old protected lines if we exceed the maximum
        self._prune_old_protected_lines()

    def _prune_old_protected_lines(self) -> None:
        """Remove oldest protected line indices if we exceed MAX_PROTECTED_LINES."""
        if len(self._protected_lines) > self.MAX_PROTECTED_LINES:
            sorted_lines = sorted(self._protected_lines)
            to_remove = len(self._protected_lines) - self.MAX_PROTECTED_LINES
            for idx in sorted_lines[:to_remove]:
                self._protected_lines.discard(idx)

    def _cleanup_protected_lines(self) -> None:
        """Remove protected lines that are out of bounds."""
        if not self._protected_lines:
            return
        
        # Filter out indices larger than current line count
        max_idx = len(self.lines) - 1
        valid_lines = {idx for idx in self._protected_lines if idx <= max_idx}
        
        if len(valid_lines) != len(self._protected_lines):
            self._protected_lines = valid_lines

    async def on_key(self, event) -> None:
        """Handle key events, delegating to overlays if active, else scrolling."""
        
        # Check for active overlays (Approval Prompt or Model Picker)
        app = getattr(self, "app", None)
        if app:
            # 1. Approval Prompt
            approval_controller = getattr(app, "_approval_controller", None)
            if approval_controller and getattr(approval_controller, "active", False):
                if event.key == "up":
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_approval_move"):
                        app._approval_move(-1)
                    return
                if event.key == "down":
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_approval_move"):
                        app._approval_move(1)
                    return
                if event.key in {"enter", "return"} and "+" not in event.key:
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_approval_confirm"):
                        app._approval_confirm()
                    return
                if event.key in {"escape", "ctrl+c"}:
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_approval_cancel"):
                        app._approval_cancel()
                    return
                return  # Swallow other keys in approval mode? Or let them pass?

            # 2. Model Picker
            model_picker = getattr(app, "_model_picker", None)
            if model_picker and getattr(model_picker, "active", False):
                if event.key == "up":
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_model_picker_move"):
                        app._model_picker_move(-1)
                    return
                if event.key == "down":
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_model_picker_move"):
                        app._model_picker_move(1)
                    return
                if event.key in {"enter", "return"} and "+" not in event.key:
                    event.stop()
                    event.prevent_default()
                    confirm = getattr(app, "_model_picker_confirm", None)
                    if confirm is not None:
                        result = confirm()
                        import inspect
                        if inspect.isawaitable(result):
                            await result
                    return
                if event.key in {"escape", "ctrl+c"}:
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_model_picker_cancel"):
                        app._model_picker_cancel()
                    return
                if event.character and event.character.lower() == "b":
                    event.stop()
                    event.prevent_default()
                    if hasattr(app, "_model_picker_back"):
                        app._model_picker_back()
                    return

        # Default scrolling behavior
        # Handle Page Up/Down (or Fn+Up/Down) with a smaller stride for finer control
        if event.key == "pageup":
            self.scroll_partial_page(direction=-1)
            event.prevent_default()
            return

        elif event.key == "pagedown":
            self.scroll_partial_page(direction=1)
            event.prevent_default()
            return

        # For other scroll keys (arrows, home, end), mark as user-scrolled
        # The default behavior will handle the actual scrolling
        elif event.key in ("up", "down", "home", "end"):
            self._user_scrolled = True
            self.auto_scroll = False

    def scroll_partial_page(self, direction: int) -> None:
        """Scroll a fraction of the viewport instead of a full page."""
        self._user_scrolled = True
        self.auto_scroll = False
        stride = max(self.size.height // 10, 3)  # 10% of viewport per page
        self.scroll_relative(y=direction * stride)

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        """Handle mouse scroll down (wheel down / two-finger swipe down)."""
        # When Option (meta) key is pressed, allow default behavior for text selection scrolling
        if event.meta:
            return  # Don't stop event, let terminal handle it
        self._user_scrolled = True
        self.auto_scroll = False
        self.scroll_relative(y=3)  # Scroll 3 lines per tick
        event.stop()

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        """Handle mouse scroll up (wheel up / two-finger swipe up)."""
        # When Option (meta) key is pressed, allow default behavior for text selection scrolling
        if event.meta:
            return  # Don't stop event, let terminal handle it
        self._user_scrolled = True
        self.auto_scroll = False
        self.scroll_relative(y=-3)  # Scroll 3 lines per tick
        self._reset_auto_scroll()  # Re-enable auto-scroll if at bottom
        event.stop()

    def on_mouse_down(self, event: MouseDown) -> None:
        """Track mouse down for drag detection."""
        self._mouse_down_pos = (event.x, event.y)

    def on_mouse_move(self, event: MouseMove) -> None:
        """Detect drag without Shift and show selection tip."""
        if self._mouse_down_pos and not event.shift:
            # User is dragging without Shift - show selection tip
            if hasattr(self.app, 'show_selection_tip'):
                self.app.show_selection_tip()
            self._mouse_down_pos = None  # Only show once per drag

    def on_mouse_up(self, event: MouseUp) -> None:
        """Clear mouse down tracking."""
        self._mouse_down_pos = None

    def _reset_auto_scroll(self) -> None:
        """Reset auto-scroll when new content arrives."""
        # When new content arrives, check if we should re-enable auto-scroll
        # If user hasn't manually scrolled away, enable auto-scroll
        if not self._user_scrolled:
            self.auto_scroll = True

        # If we're back at the bottom (within 2 lines), re-enable auto-scroll
        if self.scroll_offset.y >= self.max_scroll_y - 2:
            self._user_scrolled = False
            self.auto_scroll = True

    def add_user_message(self, message: str) -> None:
        self._message_renderer.add_user_message(message)

    def add_assistant_message(self, message: str) -> None:
        self._message_renderer.add_assistant_message(message)

    def add_system_message(self, message: str) -> None:
        self._message_renderer.add_system_message(message)

    def add_error(self, message: str) -> None:
        """Render an error message with a red bullet and clear any active spinner."""
        self.stop_spinner()  # Retain state change logic here
        self._message_renderer.add_error(message)

    def add_tool_call(self, display: Text | str, *_: Any) -> None:
        self._tool_renderer.add_tool_call(display)

    def start_tool_execution(self) -> None:
        self._tool_renderer.start_tool_execution()

    def stop_tool_execution(self, success: bool = True) -> None:
        self._tool_renderer.stop_tool_execution(success)

    def update_progress_text(self, message: str | Text) -> None:
        """Update the current progress/tool line text in-place."""
        self._tool_renderer.update_progress_text(message)

    def add_tool_result(self, result: str) -> None:
        self._tool_renderer.add_tool_result(result)

    def complete_nested_tool_call(
        self,
        tool_name: str,
        depth: int,
        parent: str,
        success: bool,
    ) -> None:
        self._tool_renderer.complete_nested_tool_call(tool_name, depth, parent, success)

    def add_nested_tree_result(
        self,
        tool_outputs: list[str],
        depth: int,
        is_last_parent: bool = True,
        has_error: bool = False,
        has_interrupted: bool = False,
    ) -> None:
        self._tool_renderer.add_nested_tree_result(
            tool_outputs, depth, is_last_parent, has_error, has_interrupted
        )

    def add_edit_diff_result(self, diff_text: str, depth: int, is_last_parent: bool = True) -> None:
        self._tool_renderer.add_edit_diff_result(diff_text, depth, is_last_parent)

    def add_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = ".",
        depth: int = 0,
    ) -> None:
        self._tool_renderer.add_bash_output_box(
            output, is_error, command, working_dir, depth
        )

    def start_streaming_bash_box(self, command: str = "", working_dir: str = ".") -> None:
        self._tool_renderer.start_streaming_bash_box(command, working_dir)

    def append_to_streaming_box(self, line: str, is_stderr: bool = False) -> None:
        self._tool_renderer.append_to_streaming_box(line, is_stderr)

    def close_streaming_bash_box(self, is_error: bool, exit_code: int) -> None:
        self._tool_renderer.close_streaming_bash_box(is_error, exit_code)

    def add_nested_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = "",
        depth: int = 1,
    ) -> None:
        self._tool_renderer.add_nested_bash_output_box(
             output, is_error, command, working_dir, depth
        )

    def add_nested_tool_call(
        self,
        display: Text | str,
        depth: int,
        parent: str,
    ) -> None:
        self._tool_renderer.add_nested_tool_call(display, depth, parent)

    # --- Thinking Spinner handling ------------------------------------------------

    # Minimum time (ms) the spinner must be visible before stopping
    MIN_VISIBLE_MS = 300
    _SPINNER_DEBUG = True  # Enable debug logging
    _SPINNER_LOG_FILE = "/tmp/spinner_debug.log"

    def _spinner_log(self, msg: str) -> None:
        """Debug log for spinner to file."""
        if self._SPINNER_DEBUG:
            import time as t
            with open(self._SPINNER_LOG_FILE, "a") as f:
                f.write(f"[{t.time():.3f}] {msg}\n")


    def _truncate_from(self, index: int) -> None:
        if index >= len(self.lines):
            return

        # Check if any protected lines would be affected
        protected_in_range = [i for i in self._protected_lines if i >= index]
        if protected_in_range:
            # Don't truncate protected lines - find the first non-protected line after index
            # or skip truncation entirely if all lines after index are protected
            non_protected = [i for i in range(index, len(self.lines)) if i not in self._protected_lines]
            if not non_protected:
                return  # All lines after index are protected, skip truncation
            # Only delete non-protected lines
            for i in sorted(non_protected, reverse=True):
                if i < len(self.lines):
                    del self.lines[i]
        else:
            del self.lines[index:]

        self._line_cache.clear()

        # Update protected line indices after deletion
        new_protected = set()
        for p in self._protected_lines:
            if p < index:
                new_protected.add(p)
            elif p in protected_in_range:
                # Recalculate position - count how many non-protected lines before this were deleted
                deleted_before = len([i for i in range(index, p) if i not in self._protected_lines])
                new_protected.add(p - deleted_before)
        self._protected_lines = new_protected

        widths: List[int] = []
        for strip in self.lines:
            cell_length = getattr(strip, "cell_length", None)
            widths.append(cell_length() if callable(cell_length) else cell_length or 0)

        self._widest_line_width = max(widths, default=0)
        self._start_line = max(0, min(self._start_line, len(self.lines)))
        self.virtual_size = Size(self._widest_line_width, len(self.lines))

        if self.auto_scroll:
            self.scroll_end(animate=False)

        self.refresh()

    def start_spinner(self, message: Text | str) -> None:
        """Show thinking spinner (delegated to SpinnerManager)."""
        if self._debug_enabled:
             # Keep debug logging if useful, or move to manager?
             pass
        self._spinner_manager.start_spinner(message)

    def update_spinner(self, message: Text | str) -> None:
        """Update the thinking message."""
        self._spinner_manager.update_spinner(message)

    def stop_spinner(self) -> None:
        """Stop the thinking spinner."""
        self._spinner_manager.stop_spinner()

    def tick_spinner(self) -> None:
        """Advance spinner animation manually."""
        self._spinner_manager.tick_spinner()
