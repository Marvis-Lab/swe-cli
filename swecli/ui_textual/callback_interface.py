"""Standardized UI callback interface for all prompt, tool call, and response handling.

This module defines the canonical interface for UI callbacks used throughout the
application. All callback implementations should inherit from BaseUICallback to
ensure consistent behavior and method signatures.

Usage:
    from swecli.ui_textual.callback_interface import BaseUICallback, UICallbackProtocol

    class MyCallback(BaseUICallback):
        def on_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> None:
            # Custom implementation
            print(f"Tool called: {tool_name}")
"""

from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class UICallbackProtocol(Protocol):
    """Protocol defining the complete UI callback interface.

    This protocol defines all methods that UI callbacks may implement.
    Use this for type hints when accepting any UI callback implementation.

    Categories:
        - Core: on_tool_call, on_tool_result (tool lifecycle)
        - Thinking: on_thinking_start, on_thinking_complete (agent state)
        - Progress: on_progress_start, on_progress_update, on_progress_complete
        - Messages: on_assistant_message, on_message
        - Special: on_interrupt, on_bash_output_line, on_debug
        - Nested: on_nested_tool_call, on_nested_tool_result (subagents)
    """

    # Core tool lifecycle
    def on_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> None:
        """Called when a tool is about to be executed."""
        ...

    def on_tool_result(
        self, tool_name: str, tool_args: Dict[str, Any], result: Any
    ) -> None:
        """Called when a tool execution completes."""
        ...

    # Thinking state
    def on_thinking_start(self) -> None:
        """Called when the agent starts thinking/processing."""
        ...

    def on_thinking_complete(self) -> None:
        """Called when the agent completes thinking/processing."""
        ...

    # Progress operations
    def on_progress_start(self, message: str) -> None:
        """Called when a progress operation starts (shows spinner)."""
        ...

    def on_progress_update(self, message: str) -> None:
        """Called to update progress text in-place."""
        ...

    def on_progress_complete(self, message: str = "", success: bool = True) -> None:
        """Called when a progress operation completes."""
        ...

    # Messages
    def on_assistant_message(self, content: str) -> None:
        """Called when the assistant provides a message."""
        ...

    def on_message(self, message: str) -> None:
        """Called to display a simple message (no spinner)."""
        ...

    # Special events
    def on_interrupt(self) -> None:
        """Called when execution is interrupted by user."""
        ...

    def on_bash_output_line(self, line: str, is_stderr: bool = False) -> None:
        """Called for each line of bash output during streaming."""
        ...

    def on_debug(self, message: str, prefix: str = "DEBUG") -> None:
        """Called to display debug information."""
        ...

    # Nested tool calls (subagents)
    def on_nested_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        depth: int,
        parent: str,
    ) -> None:
        """Called when a nested tool (from subagent) is about to execute."""
        ...

    def on_nested_tool_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        depth: int,
        parent: str,
    ) -> None:
        """Called when a nested tool (from subagent) completes."""
        ...


class BaseUICallback:
    """Base class with no-op implementations for all callback methods.

    Subclass this and override only the methods you need. All methods have
    default no-op implementations, so you don't need to implement everything.

    Example:
        class MyCallback(BaseUICallback):
            def on_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> None:
                print(f"Executing: {tool_name}")

            def on_tool_result(self, tool_name: str, tool_args: Dict[str, Any], result: Any) -> None:
                print(f"Result: {result}")
    """

    def on_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> None:
        """Called when a tool is about to be executed."""
        pass

    def on_tool_result(
        self, tool_name: str, tool_args: Dict[str, Any], result: Any
    ) -> None:
        """Called when a tool execution completes."""
        pass

    def on_thinking_start(self) -> None:
        """Called when the agent starts thinking/processing."""
        pass

    def on_thinking_complete(self) -> None:
        """Called when the agent completes thinking/processing."""
        pass

    def on_progress_start(self, message: str) -> None:
        """Called when a progress operation starts (shows spinner)."""
        pass

    def on_progress_update(self, message: str) -> None:
        """Called to update progress text in-place."""
        pass

    def on_progress_complete(self, message: str = "", success: bool = True) -> None:
        """Called when a progress operation completes."""
        pass

    def on_assistant_message(self, content: str) -> None:
        """Called when the assistant provides a message."""
        pass

    def on_message(self, message: str) -> None:
        """Called to display a simple message (no spinner)."""
        pass

    def on_interrupt(self) -> None:
        """Called when execution is interrupted by user."""
        pass

    def on_bash_output_line(self, line: str, is_stderr: bool = False) -> None:
        """Called for each line of bash output during streaming."""
        pass

    def on_debug(self, message: str, prefix: str = "DEBUG") -> None:
        """Called to display debug information."""
        pass

    def on_nested_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        depth: int,
        parent: str,
    ) -> None:
        """Called when a nested tool (from subagent) is about to execute."""
        pass

    def on_nested_tool_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        depth: int,
        parent: str,
    ) -> None:
        """Called when a nested tool (from subagent) completes."""
        pass
