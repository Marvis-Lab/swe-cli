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
    TerminalBoxRenderer,
)
from swecli.ui_textual.widgets.conversation.spinner_manager import DefaultSpinnerManager
from swecli.ui_textual.widgets.conversation.message_renderer import DefaultMessageRenderer


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
        self._tool_display: Text | None = None
        self._tool_spinner_timer: Timer | None = None
        self._spinner_active = False
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
        # Terminal box renderer (unified rendering for main/subagent output)
        self._box_renderer = TerminalBoxRenderer(self._get_box_width)
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
        return

    def on_unmount(self) -> None:
        if self._tool_spinner_timer is not None:
            self._tool_spinner_timer.stop()
            self._tool_spinner_timer = None
            self._tool_spinner_timer = None
        
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
        # Add blank line before tool call if previous line has content
        if self._last_line_has_content:
            self.write(Text(""))

        if isinstance(display, Text):
            self._tool_display = display.copy()
        else:
            self._tool_display = Text(str(display), style="white")

        self._tool_call_start = len(self.lines)
        self._tool_timer_start = None
        self._tool_last_elapsed = None
        self._write_tool_call_line("⏺")

    def start_tool_execution(self) -> None:
        if self._tool_display is None:
            return

        self._spinner_active = True
        self._spinner_index = 0
        self._tool_timer_start = time.monotonic()
        self._tool_last_elapsed = None
        self._render_tool_spinner_frame()
        self._schedule_tool_spinner()

    def stop_tool_execution(self, success: bool = True) -> None:
        self._spinner_active = False
        if self._tool_timer_start is not None:
            elapsed_raw = time.monotonic() - self._tool_timer_start
            self._tool_last_elapsed = max(round(elapsed_raw), 0)
        else:
            self._tool_last_elapsed = None
        self._tool_timer_start = None
        if self._tool_call_start is not None and self._tool_display is not None:
            self._replace_tool_call_line("⏺", success=success)

        self._tool_display = None
        self._tool_call_start = None
        self._spinner_index = 0
        # Cancel both Textual and thread timers
        if self._tool_spinner_timer is not None:
            self._tool_spinner_timer.stop()
            self._tool_spinner_timer = None
        if self._tool_thread_timer is not None:
            self._tool_thread_timer.cancel()
            self._tool_thread_timer = None

    def update_progress_text(self, message: str | Text) -> None:
        """Update the current progress/tool line text in-place.

        This updates the displayed text while keeping the spinner running
        and the timer accumulating. Use this for multi-step progress updates
        that should appear on the same line.

        Args:
            message: New text to display (replaces current text)
        """
        if self._tool_call_start is None:
            # No active progress line - start a new one
            self.add_tool_call(message)
            self.start_tool_execution()
            return

        # Update the display text
        if isinstance(message, Text):
            self._tool_display = message.copy()
        else:
            self._tool_display = Text(str(message), style="white")

        # Re-render the spinner frame with new text
        if self._spinner_active:
            self._render_tool_spinner_frame()

    def add_tool_result(self, result: str) -> None:
        try:
            result_plain = Text.from_markup(result).plain
        except Exception:
            result_plain = result

        header, diff_lines = self._extract_edit_payload(result_plain)
        if header:
            self._write_edit_result(header, diff_lines)
        else:
            self._write_generic_tool_result(result_plain)

        self.write(Text(""))

    def add_nested_tool_call(
        self,
        display: Text | str,
        depth: int,
        parent: str,
    ) -> None:
        """Add a nested tool call with indentation for subagent display.

        Args:
            display: The tool call display text
            depth: Nesting depth level (1 = direct child of main agent)
            parent: Name/identifier of the parent subagent
        """
        # Add blank line before nested tool call if previous line has content
        if self.lines and hasattr(self.lines[-1], 'plain'):
            last_plain = self.lines[-1].plain.strip() if self.lines[-1].plain else ""
            if last_plain:
                self.write(Text(""))

        if isinstance(display, Text):
            tool_text = display.copy()
        else:
            # Use dim style for nested tool calls to match nested result styling
            tool_text = Text(str(display), style="dim")

        # Build indented line with spinner - START with first color (brightest)
        formatted = Text()
        indent = "  " * depth
        formatted.append(indent)
        formatted.append(f"{self._nested_spinner_char} ", style=self._nested_color_gradient[0])
        formatted.append_text(tool_text)
        formatted.append(" (0s)", style=GREY)  # Initial elapsed time

        self.write(formatted, scroll_end=True, animate=False)

        # Track this nested tool call for animation
        self._nested_tool_line = len(self.lines) - 1
        self._nested_tool_text = tool_text.copy()
        self._nested_tool_depth = depth
        self._nested_pulse_bright = False
        self._nested_pulse_counter = 0
        self._nested_color_index = 0
        self._nested_tool_timer_start = time.monotonic()

        # Start independent timer for nested tool animation
        self._start_nested_tool_timer()

    def _start_nested_tool_timer(self) -> None:
        """Start the independent timer for nested tool spinner animation."""
        import logging
        _log = logging.getLogger(__name__)
        _log.debug(f"[TIMER] _start_nested_tool_timer called, timer_start={self._nested_tool_timer_start}")

        if self._nested_tool_timer is not None:
            self._nested_tool_timer.stop()
        if self._nested_tool_thread_timer is not None:
            self._nested_tool_thread_timer.cancel()
            self._nested_tool_thread_timer = None
        # Run first animation frame IMMEDIATELY to ensure animation shows
        # even for fast tools that complete in <100ms
        self._animate_nested_tool_spinner()

    def _on_nested_tool_thread_tick(self) -> None:
        """Fallback tick via threading.Timer when Textual event loop is blocked."""
        if self._nested_tool_line is None or self._nested_tool_text is None:
            return
        # Use call_from_thread to safely run animation on UI thread
        try:
            self.app.call_from_thread(self._animate_nested_tool_spinner)
        except Exception:
            pass  # App may be shutting down

    def _animate_nested_tool_spinner(self) -> None:
        """Animate the nested tool spinner independently."""
        import logging
        _log = logging.getLogger(__name__)

        # Cancel thread timer if this tick came from Textual timer
        if self._nested_tool_thread_timer is not None:
            self._nested_tool_thread_timer.cancel()
            self._nested_tool_thread_timer = None

        if self._nested_tool_line is None or self._nested_tool_text is None:
            return

        elapsed = 0
        if self._nested_tool_timer_start is not None:
            elapsed = round(time.monotonic() - self._nested_tool_timer_start)
        _log.debug(f"[TIMER] _animate_nested_tool_spinner: elapsed={elapsed}s")

        # Update color gradient frame (smooth pulse for nested tools)
        self._nested_color_index = (self._nested_color_index + 1) % len(self._nested_color_gradient)

        # Render the updated line
        self._render_nested_tool_line()

        # Schedule next frame with dual-timer pattern (slow for ultra-smooth gradient)
        interval = 0.15  # 150ms per frame = ultra smooth breathing

        # Primary: Textual timer (works when event loop is free)
        self._nested_tool_timer = self.set_timer(interval, self._animate_nested_tool_spinner)

        # Fallback: threading.Timer (bypasses blocked event loop during tool execution)
        self._nested_tool_thread_timer = threading.Timer(interval, self._on_nested_tool_thread_tick)
        self._nested_tool_thread_timer.daemon = True
        self._nested_tool_thread_timer.start()

    def _render_nested_tool_line(self) -> None:
        """Render the nested tool line with current spinner frame and elapsed time."""
        if self._nested_tool_line is None or self._nested_tool_text is None:
            return

        if self._nested_tool_line >= len(self.lines):
            return

        # Calculate elapsed time
        elapsed = 0
        if self._nested_tool_timer_start is not None:
            elapsed = round(time.monotonic() - self._nested_tool_timer_start)

        # Build the animated line (color gradient pulse for nested tools)
        formatted = Text()
        indent = "  " * self._nested_tool_depth
        formatted.append(indent)
        color = self._nested_color_gradient[self._nested_color_index]
        formatted.append(f"{self._nested_spinner_char} ", style=color)
        formatted.append_text(self._nested_tool_text.copy())
        formatted.append(f" ({elapsed}s)", style=GREY)

        # Convert Text to Strip for in-place storage
        from rich.console import Console
        from textual.strip import Strip

        console = Console(width=1000, force_terminal=True, no_color=False)
        segments = list(formatted.render(console))
        strip = Strip(segments)

        # Update line in-place
        self.lines[self._nested_tool_line] = strip
        self._line_cache.clear()
        self.refresh_line(self._nested_tool_line)
        if hasattr(self, 'app') and self.app is not None:
            self.app.refresh()

    def complete_nested_tool_call(
        self,
        tool_name: str,
        depth: int,
        parent: str,
        success: bool,
    ) -> None:
        """Mark a nested tool call as complete.

        Args:
            tool_name: Name of the tool that completed
            depth: Nesting depth level
            parent: Name/identifier of the parent subagent
            success: Whether the tool execution succeeded
        """
        import logging
        _log = logging.getLogger(__name__)
        elapsed = 0
        if self._nested_tool_timer_start is not None:
            elapsed = round(time.monotonic() - self._nested_tool_timer_start)
        _log.debug(f"[TIMER] complete_nested_tool_call: tool={tool_name}, elapsed={elapsed}s, timer_start={self._nested_tool_timer_start}")

        # Stop both Textual and thread timers
        if self._nested_tool_timer is not None:
            self._nested_tool_timer.stop()
            self._nested_tool_timer = None
        if self._nested_tool_thread_timer is not None:
            self._nested_tool_thread_timer.cancel()
            self._nested_tool_thread_timer = None

        # Update the line to final state (green for success, red for failure)
        if self._nested_tool_line is not None and self._nested_tool_text is not None:
            self._render_nested_tool_final(success)

        # Clear nested tool tracking
        self._nested_tool_line = None
        self._nested_tool_text = None
        self._nested_tool_timer_start = None

    def _render_nested_tool_final(self, success: bool) -> None:
        """Render the final state of nested tool line with bullet."""
        import logging
        _log = logging.getLogger(__name__)

        if self._nested_tool_line is None or self._nested_tool_text is None:
            _log.debug("[TIMER] _render_nested_tool_final: SKIP - nested_tool_line or nested_tool_text is None")
            return

        if self._nested_tool_line >= len(self.lines):
            _log.debug(f"[TIMER] _render_nested_tool_final: SKIP - line index {self._nested_tool_line} >= {len(self.lines)}")
            return

        # Calculate final elapsed time
        # Use round() instead of int() to properly round to nearest second
        # (int() truncates, so 0.9s would show as 0s instead of 1s)
        elapsed = 0
        if self._nested_tool_timer_start is not None:
            elapsed = round(time.monotonic() - self._nested_tool_timer_start)

        # Build the final line with solid bullet
        formatted = Text()
        indent = "  " * self._nested_tool_depth
        formatted.append(indent)
        bullet_style = "green" if success else ERROR
        formatted.append("⏺ ", style=bullet_style)
        formatted.append_text(self._nested_tool_text.copy())
        formatted.append(f" ({elapsed}s)", style=GREY)

        # Convert Text to Strip for in-place storage
        from rich.console import Console
        from textual.strip import Strip

        console = Console(width=1000, force_terminal=True, no_color=False)
        segments = list(formatted.render(console))
        strip = Strip(segments)

        # Update line in-place
        self.lines[self._nested_tool_line] = strip
        self._line_cache.clear()
        self.refresh_line(self._nested_tool_line)
        if hasattr(self, 'app') and self.app is not None:
            self.app.refresh()

    def add_todo_sub_result(self, text: str, depth: int, is_last_parent: bool = True) -> None:
        """Add a single sub-result line for todo operations.

        Args:
            text: The sub-result text (e.g., "○ Create project structure")
            depth: Nesting depth for indentation
            is_last_parent: If True, no vertical continuation line (parent is last tool)
        """
        formatted = Text()
        indent = "  " * depth
        formatted.append(indent)
        # Use │ for vertical continuation only when more tools are coming
        prefix = "    └─ " if is_last_parent else "│   └─ "
        formatted.append(prefix, style="dim")
        formatted.append(text, style="dim")
        self.write(formatted, scroll_end=True, animate=False)

    def add_todo_sub_results(self, items: list, depth: int, is_last_parent: bool = True) -> None:
        """Add multiple sub-result lines for todo list operations.

        Args:
            items: List of (symbol, title) tuples
            depth: Nesting depth for indentation
            is_last_parent: If True, no vertical continuation line (parent is last tool)
        """
        indent = "  " * depth

        for i, (symbol, title) in enumerate(items):
            formatted = Text()
            formatted.append(indent)

            is_last_item = i == len(items) - 1
            # Use │ for vertical continuation only when more tools are coming
            if is_last_parent:
                prefix = "    └─ " if is_last_item else "    ├─ "
            else:
                prefix = "│   └─ " if is_last_item else "│   ├─ "

            formatted.append(prefix, style="dim")
            formatted.append(f"{symbol} {title}", style="dim")
            self.write(formatted, scroll_end=True, animate=False)

    def add_nested_tool_sub_results(self, lines: List[str], depth: int, is_last_parent: bool = True) -> None:
        """Add tool result lines with proper nesting indentation.

        This is the unified method for displaying subagent tool results,
        using the same formatting as the main agent via StyleFormatter.

        Args:
            lines: List of result lines from StyleFormatter._format_*_result() methods
            depth: Nesting depth for indentation
            is_last_parent: If True, no vertical continuation line (parent is last tool)
        """
        indent = "  " * depth

        # Flatten any multi-line strings into individual lines
        all_lines = []
        for line in lines:
            if '\n' in line:
                all_lines.extend(line.split('\n'))
            else:
                all_lines.append(line)

        # Filter trailing empty lines
        while all_lines and not all_lines[-1].strip():
            all_lines.pop()

        # Filter out empty lines and track non-empty ones for proper tree formatting
        non_empty_lines = [(i, line) for i, line in enumerate(all_lines) if line.strip()]

        # Check if any line contains error or interrupted markers - if so, all lines should be styled accordingly
        has_error = any(TOOL_ERROR_SENTINEL in line for _, line in non_empty_lines)
        has_interrupted = any("::interrupted::" in line for _, line in non_empty_lines)

        for idx, (orig_i, line) in enumerate(non_empty_lines):
            formatted = Text()
            formatted.append(indent)

            is_last_item = idx == len(non_empty_lines) - 1
            # Use │ for vertical continuation only when more tools are coming
            if is_last_parent:
                prefix = "    └─ " if is_last_item else "    ├─ "
            else:
                prefix = "│   └─ " if is_last_item else "│   ├─ "
            formatted.append(prefix, style="dim")

            # Strip markers from content
            clean_line = line.replace(TOOL_ERROR_SENTINEL, "").replace("::interrupted::", "").strip()
            # Strip ANSI codes for nested display (they don't render well in tree format)
            clean_line = re.sub(r"\x1b\[[0-9;]*m", "", clean_line)

            # Apply consistent styling based on error state
            if has_interrupted:
                formatted.append(clean_line, style=f"bold {ERROR}")
            elif has_error:
                formatted.append(clean_line, style=ERROR)
            else:
                formatted.append(clean_line, style="dim")

            self.write(formatted, scroll_end=True, animate=False)

    def add_edit_diff_result(self, diff_text: str, depth: int, is_last_parent: bool = True) -> None:
        """Add diff lines for edit_file result in subagent output.

        Args:
            diff_text: The unified diff text
            depth: Nesting depth for indentation
            is_last_parent: If True, no vertical continuation line (parent is last tool)
        """
        from swecli.ui_textual.formatters_internal.utils import DiffParser

        diff_entries = DiffParser.parse_unified_diff(diff_text)
        if not diff_entries:
            return

        indent = "  " * depth

        for i, (entry_type, line_no, content) in enumerate(diff_entries):
            formatted = Text()
            formatted.append(indent)

            is_last_item = i == len(diff_entries) - 1
            # Use │ for vertical continuation only when more tools are coming
            if is_last_parent:
                prefix = "    └─ " if is_last_item else "    ├─ "
            else:
                prefix = "│   └─ " if is_last_item else "│   ├─ "
            formatted.append(prefix, style="dim")

            if entry_type == "hunk":
                formatted.append(content, style="dim")
            elif entry_type == "add":
                display_no = f"{line_no:>4} " if line_no is not None else "     "
                formatted.append(display_no, style="dim")
                formatted.append("+ ", style="green")
                formatted.append(content.replace("\t", "    "), style="green")
            elif entry_type == "del":
                display_no = f"{line_no:>4} " if line_no is not None else "     "
                formatted.append(display_no, style="dim")
                formatted.append("- ", style=ERROR)
                formatted.append(content.replace("\t", "    "), style=ERROR)
            else:
                display_no = f"{line_no:>4} " if line_no is not None else "     "
                formatted.append(display_no, style="dim")
                formatted.append("  ", style="dim")
                formatted.append(content.replace("\t", "    "), style="dim")

            self.write(formatted, scroll_end=True, animate=False)

    def render_approval_prompt(self, lines: list[Text]) -> None:
        if self._approval_start is None:
            self._approval_start = len(self.lines)

        self._truncate_from(self._approval_start)

        for line in lines:
            self.write(line, scroll_end=True, animate=False)

    def clear_approval_prompt(self) -> None:
        if self._approval_start is None:
            return

        self._truncate_from(self._approval_start)
        self._approval_start = None

    # --- Private helpers -------------------------------------------------

    def _write_generic_tool_result(self, text: str) -> None:
        lines = text.rstrip("\n").splitlines() or [text]
        for i, raw_line in enumerate(lines):
            # First line gets ⎿ prefix, subsequent lines get spaces for alignment
            prefix = "    ⎿  " if i == 0 else "       "
            line = Text(prefix, style=GREY)
            message = raw_line.rstrip("\n")
            is_error = False
            is_interrupted = False
            if message.startswith(TOOL_ERROR_SENTINEL):
                is_error = True
                message = message[len(TOOL_ERROR_SENTINEL):].lstrip()
            elif message.startswith("::interrupted::"):
                is_interrupted = True
                message = message[len("::interrupted::"):].lstrip()

            if is_interrupted:
                line.append(message, style=f"bold {ERROR}")
            else:
                line.append(message, style=ERROR if is_error else GREY)
            self.write(line)

    def add_bash_output_box(
        self,
        output: str,
        is_error: bool = False,
        command: str = "",
        working_dir: str = ".",
        depth: int = 0,
    ) -> None:
        """Render bash command output in VS Code Terminal style box.

        Args:
            output: The full bash output string
            is_error: Whether this is an error output (uses red styling)
            command: The command that was executed
            working_dir: The working directory
            depth: Nesting depth for subagent display
        """
        lines = output.rstrip("\n").splitlines()
        config = TerminalBoxConfig(
            command=command,
            working_dir=working_dir,
            depth=depth,
            is_error=is_error,
            box_width=self._get_box_width(),
        )
        for text_line in self._box_renderer.render_complete_box(lines, config):
            self.write(text_line)

    # --- Streaming bash box methods -------------------------------------------

    def _get_box_width(self) -> int:
        """Get box width based on widget size for dynamic sizing."""
        # Get widget width, leave margin for "  ⎿ " prefix (4 chars)
        available = (self.size.width or 120) - 4
        # Clamp between reasonable min/max
        return max(60, min(available, 120))

    def start_streaming_bash_box(self, command: str = "", working_dir: str = ".") -> None:
        """Start a VS Code-style terminal box with TERMINAL label and prompt line."""
        config = TerminalBoxConfig(
            command=command,
            working_dir=working_dir,
            depth=0,
            is_error=False,  # Unknown during streaming, always use default border
            box_width=self._get_box_width(),
        )
        
        # Store config for use in append and close
        self._streaming_box_config = config
        self._streaming_box_top_line = len(self.lines)
        
        # Render top border
        self.write(self._box_renderer.render_top_border(config))
        
        # Render padding line
        self.write(self._box_renderer.render_padding_line(config))
        
        # Render prompt line
        self._streaming_box_header_line = len(self.lines)
        self.write(self._box_renderer.render_prompt_line(config))
        
        # Store data for rebuild on close
        self._streaming_box_command = command
        self._streaming_box_working_dir = working_dir
        self._streaming_box_content_lines = []

    def append_to_streaming_box(self, line: str, is_stderr: bool = False) -> None:
        """Append a content line to the streaming box."""
        config = getattr(self, '_streaming_box_config', None)
        if config is None:
            # Fallback if config not set (shouldn't happen in normal flow)
            config = TerminalBoxConfig(box_width=self._get_box_width())
        
        # Render content line (no error styling during streaming)
        self.write(self._box_renderer.render_content_line(line, config, apply_error_style=False))
        
        # Store for rebuild on close
        self._streaming_box_content_lines.append((line, is_stderr))

    def close_streaming_bash_box(self, is_error: bool, exit_code: int) -> None:
        """Close box with padding, bottom border, and apply truncation if needed."""
        config = getattr(self, '_streaming_box_config', None)
        if config is None:
            # Fallback if config not set
            config = TerminalBoxConfig(box_width=self._get_box_width())

        # Check if truncation is needed (main agent uses MAIN_AGENT limits)
        content_lines = [line for line, _ in self._streaming_box_content_lines]
        head_count = self._box_renderer.MAIN_AGENT_HEAD_LINES
        tail_count = self._box_renderer.MAIN_AGENT_TAIL_LINES
        max_lines = head_count + tail_count

        if len(content_lines) > max_lines and self._streaming_box_top_line is not None:
            # Rebuild the box with truncation
            self._rebuild_streaming_box_with_truncation(is_error, config, content_lines)
        else:
            # No truncation needed - just close normally
            self.write(self._box_renderer.render_padding_line(config))
            self.write(self._box_renderer.render_bottom_border(config))

        # Reset state
        self._streaming_box_header_line = None
        self._streaming_box_top_line = None
        self._streaming_box_config = None
        self._streaming_box_command = ""
        self._streaming_box_working_dir = "."
        self._streaming_box_content_lines = []

    def _rebuild_streaming_box_with_truncation(
        self,
        is_error: bool,
        config: TerminalBoxConfig,
        content_lines: list[str],
    ) -> None:
        """Rebuild the streaming box with head+tail truncation.

        Removes all streamed content lines and replaces them with truncated output.
        """
        if self._streaming_box_top_line is None:
            return

        # Remove all lines from top of box to current position
        self._truncate_from(self._streaming_box_top_line)

        # Create new config with error state
        new_config = TerminalBoxConfig(
            command=self._streaming_box_command,
            working_dir=self._streaming_box_working_dir,
            depth=0,  # Main agent streaming boxes are depth=0
            is_error=is_error,
            box_width=config.box_width,
        )

        # Render complete box with truncation (render_complete_box applies truncation)
        for text_line in self._box_renderer.render_complete_box(content_lines, new_config):
            self.write(text_line)

    def add_nested_bash_output_box(
        self,
        output: str,
        is_error: bool,
        exit_code: int,
        command: str = "",
        working_dir: str = ".",
        depth: int = 0,
    ) -> None:
        """Render nested bash command output in VS Code Terminal style.

        Uses same visual format as streaming box but renders complete output at once.

        Args:
            output: The full bash output string
            is_error: Whether this is an error output
            exit_code: The command exit code
            command: The command that was executed
            working_dir: The working directory
            depth: Nesting depth for indentation
        """
        # Delegate to add_bash_output_box - they're now identical
        self.add_bash_output_box(
            output=output,
            is_error=is_error,
            command=command,
            working_dir=working_dir,
            depth=depth,
        )

    def _write_edit_result(self, header: str, diff_lines: list[str]) -> None:
        if not diff_lines:
            return

        self.write(Text(header, style=f"bold {GREY}"))
        match = re.search(r"Edit(?:ed)?\s+[\"']?([^\s\"']+)", header)
        title = match.group(1) if match else "diff"

        rendered_lines: List[Text] = []
        for raw_line in diff_lines:
            display = raw_line.rstrip("\n")
            if not display.strip():
                rendered_lines.append(Text(""))
                continue

            stripped = display.lstrip()
            style = GREY
            if stripped.startswith("+"):
                style = "green"
            elif stripped.startswith("-"):
                style = ERROR
            elif stripped.startswith(("@@", "diff ", "index ", "---", "+++")):
                style = "cyan"
            rendered_lines.append(Text(display, style=style))

        panel = Panel(
            Group(*rendered_lines),
            border_style=GREY,
            padding=(0, 2),
            title=title,
            title_align="left",
        )
        self.write(panel)

    def _strip_tool_prefix(self, value: str) -> str:
        return re.sub(r"^\s*[⎿⏺•]\s+", "", value)

    def _extract_edit_payload(self, text: str) -> Tuple[str | None, list[str]]:
        lines = text.splitlines()
        if not lines:
            return None, []

        header = None
        payload_start = 0

        for idx, line in enumerate(lines):
            cleaned = self._strip_tool_prefix(line).strip()
            if not cleaned:
                continue
            if cleaned.startswith("Edit(") or cleaned.startswith("Edited "):
                header = cleaned
                payload_start = idx + 1
            break

        if not header:
            return None, []

        diff_lines = [
            self._strip_tool_prefix(ln.rstrip("\n"))
            for ln in lines[payload_start:]
        ]
        return header, diff_lines

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

            self._widest_line_width = max(widths, default=0)
            self.virtual_size = Size(self._widest_line_width, len(self.lines))
            if self.auto_scroll:
                self.scroll_end(animate=False)
        else:
            self._spinner_start = len(self.lines)

        # Update _last_line_has_content to reflect actual last line state
        # This prevents add_tool_call() from seeing stale state
        if self.lines:
            last_line = self.lines[-1]
            # Check Strip objects (RichLog stores lines as Strip)
            if hasattr(last_line, '_segments'):
                segments = last_line._segments
                if len(segments) == 0:
                    self._last_line_has_content = False
                elif len(segments) == 1 and not segments[0].text.strip():
                    self._last_line_has_content = False
                else:
                    # Has content if any segment has non-empty text
                    self._last_line_has_content = any(s.text.strip() for s in segments)
            elif hasattr(last_line, 'plain'):
                self._last_line_has_content = bool(last_line.plain.strip())
            else:
                self._last_line_has_content = False
        else:
            self._last_line_has_content = False

        if preserve_index:
            self._spinner_line_count = 0
        else:
            self._spinner_start = None
            self._spinner_line_count = 0


    # --- Spinner handling ------------------------------------------------

    def _render_tool_spinner_frame(self) -> None:
        if self._tool_call_start is None or self._tool_display is None:
            return

        spinner_char = self._spinner_chars[self._spinner_index]
        self._replace_tool_call_line(spinner_char)

    def _replace_tool_call_line(self, prefix: str, success: bool = True) -> None:
        """Replace the tool call line in-place, preserving its position."""
        if self._tool_call_start is None or self._tool_display is None:
            return

        if self._tool_call_start >= len(self.lines):
            # Line index out of bounds, fall back to append
            self._tool_call_start = len(self.lines)
            self._write_tool_call_line(prefix)
            self._tool_call_start = len(self.lines) - 1
            return

        # Build the new line content
        formatted = Text()
        if prefix == "⏺":
            style = "green" if success else ERROR
        else:
            style = "bright_cyan"
        formatted.append(f"{prefix} ", style=style)
        if self._tool_display is not None:
            formatted += self._tool_display.copy()
        timer = self._format_tool_timer()
        if timer is not None:
            formatted.append_text(timer)

        # Convert Text to Strip for in-place storage in RichLog
        from rich.console import Console
        from textual.strip import Strip

        # Use very large width and no_wrap to prevent text wrapping that causes corruption
        # The actual display will handle truncation at render time
        console = Console(width=1000, force_terminal=True, no_color=False)
        # Render with explicit options to avoid wrapping
        with console.capture() as capture:
            console.print(formatted, end="", overflow="ignore", no_wrap=True)
        # Get segments directly from the Text object instead of console render
        segments = list(formatted.render(console))
        strip = Strip(segments)

        # Update the line at the original position (in-place)
        self.lines[self._tool_call_start] = strip

        # Clear line cache for this line
        self._line_cache.clear()

        # Use RichLog's built-in refresh_line to update just this line
        self.refresh_line(self._tool_call_start)

        # Force screen compositor to update immediately (safely for tests)
        try:
            app = self.app
        except Exception:
            app = None
        
        if app is not None and hasattr(app, "refresh"):
            app.refresh()

    def _write_tool_call_line(self, prefix: str) -> None:
        formatted = Text()
        style = "green" if prefix == "⏺" else "bright_cyan"
        formatted.append(f"{prefix} ", style=style)
        timer = self._format_tool_timer()
        if self._tool_display is not None:
            formatted += self._tool_display.copy()
        if timer is not None:
            formatted.append_text(timer)
        self.write(formatted, scroll_end=False, animate=False)

    def _tool_elapsed_seconds(self) -> int | None:
        if self._spinner_active and self._tool_timer_start is not None:
            return max(round(time.monotonic() - self._tool_timer_start), 0)
        if self._tool_last_elapsed is not None:
            return self._tool_last_elapsed
        return None

    def _format_tool_timer(self) -> Text | None:
        elapsed = self._tool_elapsed_seconds()
        if elapsed is None:
            return None
        return Text(f" ({elapsed}s)", style=GREY)

    def _schedule_tool_spinner(self) -> None:
        """Schedule next tool spinner animation tick with dual-timer pattern.

        Uses both Textual's set_timer (for when event loop is free) and
        threading.Timer (fallback when event loop is blocked by tool execution).
        """
        if not self._spinner_active:
            return

        # Cancel existing timers
        if self._tool_spinner_timer is not None:
            self._tool_spinner_timer.stop()
        if self._tool_thread_timer is not None:
            self._tool_thread_timer.cancel()
            self._tool_thread_timer = None

        interval = 0.12  # seconds

        # Primary: Textual timer (works when event loop is free)
        self._tool_spinner_timer = self.set_timer(interval, self._animate_tool_spinner)

        # Fallback: threading.Timer (bypasses blocked event loop during tool execution)
        self._tool_thread_timer = threading.Timer(interval, self._on_tool_thread_tick)
        self._tool_thread_timer.daemon = True
        self._tool_thread_timer.start()

    def _on_tool_thread_tick(self) -> None:
        """Fallback tick via threading.Timer when Textual event loop is blocked."""
        if not self._spinner_active:
            return
        # Use call_from_thread to safely run animation on UI thread
        try:
            self.app.call_from_thread(self._animate_tool_spinner)
        except Exception:
            pass  # App may be shutting down

    def _animate_tool_spinner(self) -> None:
        """Animate the tool spinner (advances frame, updates display)."""
        # Cancel thread timer if this tick came from Textual timer
        # (prevents double-tick when both timers fire)
        if self._tool_thread_timer is not None:
            self._tool_thread_timer.cancel()
            self._tool_thread_timer = None

        if not self._spinner_active or self._tool_display is None or self._tool_call_start is None:
            return

        self._render_tool_spinner_frame()
        self._spinner_index = (self._spinner_index + 1) % len(self._spinner_chars)

        # Note: Nested tool calls now have their own independent timer
        # via _animate_nested_tool_spinner, so we don't pulse them here anymore

        self._schedule_tool_spinner()


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
