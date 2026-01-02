"""Base UI callback interface and protocol definitions.

This module provides the abstract interface for UI callbacks used throughout
the application. The Protocol defines the expected methods, while BaseUICallback
provides a no-op implementation suitable for testing or when no UI is attached.
"""

from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class UICallbackProtocol(Protocol):
    """Protocol defining the UI callback interface.

    Implementations should provide methods to handle various UI events
    such as thinking indicators, tool calls, progress updates, etc.
    """

    def on_thinking_start(self) -> None:
        """Called when the agent starts thinking."""
        ...

    def on_thinking_complete(self) -> None:
        """Called when the agent completes thinking."""
        ...

    def on_assistant_message(self, content: str) -> None:
        """Called when assistant provides a message."""
        ...

    def on_message(self, message: str) -> None:
        """Called to display a general message."""
        ...

    def on_progress_start(self, message: str) -> None:
        """Called when a progress indicator should start."""
        ...

    def on_progress_update(self, message: str) -> None:
        """Called to update the progress message."""
        ...

    def on_progress_complete(self, message: str = "", success: bool = True) -> None:
        """Called when a progress indicator should stop."""
        ...

    def on_interrupt(self) -> None:
        """Called when execution is interrupted."""
        ...

    def on_bash_output_line(self, line: str, is_stderr: bool = False) -> None:
        """Called for each line of bash output."""
        ...

    def on_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> None:
        """Called when a tool call is about to be executed."""
        ...

    def on_tool_result(
        self, tool_name: str, tool_args: Dict[str, Any], result: Any
    ) -> None:
        """Called when a tool execution completes."""
        ...

    def on_nested_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        depth: int = 1,
        parent: str = "",
    ) -> None:
        """Called when a nested/subagent tool call starts."""
        ...

    def on_nested_tool_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        depth: int = 1,
        parent: str = "",
    ) -> None:
        """Called when a nested/subagent tool call completes."""
        ...

    def on_debug(self, message: str, prefix: str = "DEBUG") -> None:
        """Called to display debug information."""
        ...


class BaseUICallback:
    """Base implementation of UI callback with no-op methods.

    This class provides empty implementations of all callback methods,
    making it suitable for:
    - Testing scenarios where no UI feedback is needed
    - Fallback when the real UI is not available
    - Base class for partial implementations
    """

    def on_thinking_start(self) -> None:
        """Called when the agent starts thinking."""
        pass

    def on_thinking_complete(self) -> None:
        """Called when the agent completes thinking."""
        pass

    def on_assistant_message(self, content: str) -> None:
        """Called when assistant provides a message."""
        pass

    def on_message(self, message: str) -> None:
        """Called to display a general message."""
        pass

    def on_progress_start(self, message: str) -> None:
        """Called when a progress indicator should start."""
        pass

    def on_progress_update(self, message: str) -> None:
        """Called to update the progress message."""
        pass

    def on_progress_complete(self, message: str = "", success: bool = True) -> None:
        """Called when a progress indicator should stop."""
        pass

    def on_interrupt(self) -> None:
        """Called when execution is interrupted."""
        pass

    def on_bash_output_line(self, line: str, is_stderr: bool = False) -> None:
        """Called for each line of bash output."""
        pass

    def on_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> None:
        """Called when a tool call is about to be executed."""
        pass

    def on_tool_result(
        self, tool_name: str, tool_args: Dict[str, Any], result: Any
    ) -> None:
        """Called when a tool execution completes."""
        pass

    def on_nested_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        depth: int = 1,
        parent: str = "",
    ) -> None:
        """Called when a nested/subagent tool call starts."""
        pass

    def on_nested_tool_result(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        depth: int = 1,
        parent: str = "",
    ) -> None:
        """Called when a nested/subagent tool call completes."""
        pass

    def on_debug(self, message: str, prefix: str = "DEBUG") -> None:
        """Called to display debug information."""
        pass


__all__ = ["UICallbackProtocol", "BaseUICallback"]
