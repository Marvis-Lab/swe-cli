"""Progress mixin for subagent commands.

This module provides a minimal mixin with standardized progress display helpers
for subagent-powered commands. Commands retain full control over their execution
flow while using consistent progress messaging.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class CommandPhase(Enum):
    """Standard phases for subagent command execution."""

    LOADING = "loading"  # Loading data/config
    CONFIGURING = "config"  # Setting up environment
    EXECUTING = "exec"  # Running subagent
    EXTRACTING = "extract"  # Extracting results
    VERIFYING = "verify"  # Verifying output
    COMPLETE = "complete"  # Done


class SubagentProgressMixin:
    """Mixin providing standardized progress display for subagent commands.

    This mixin adds progress helpers to any command class. The implementing class
    must set `self.ui_callback` to use these helpers.

    Example:
        class MyCommand(SubagentProgressMixin):
            def __init__(self, ui_callback=None):
                self.ui_callback = ui_callback

            def execute(self):
                self.show_progress("Loading dataset...", CommandPhase.LOADING)
                # ... do work ...
                self.complete_progress("Dataset loaded")

                self.show_spawn_header("My-Agent", "Process data")
                # ... spawn subagent ...
    """

    ui_callback: Optional[Any]  # Must be set by implementing class

    def show_progress(
        self, message: str, phase: Optional[CommandPhase] = None
    ) -> None:
        """Display progress message with optional phase prefix.

        Args:
            message: The progress message to display
            phase: Optional phase enum for categorization
        """
        if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
            display = f"[{phase.value}] {message}" if phase else message
            self.ui_callback.on_progress_start(display)

    def complete_progress(self, message: str) -> None:
        """Complete current progress phase with a message.

        Args:
            message: The completion message to display
        """
        if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
            self.ui_callback.on_progress_complete(message)

    def show_spawn_header(self, subagent_type: str, description: str) -> None:
        """Show standardized spawn header for subagent execution.

        This displays the subagent spawn as a tool call, which the UI renders
        with appropriate formatting and nesting.

        Args:
            subagent_type: The type of subagent (e.g., "Paper2Code", "Issue-Resolver")
            description: Brief description of what the subagent will do
        """
        if self.ui_callback and hasattr(self.ui_callback, "on_tool_call"):
            self.ui_callback.on_tool_call(
                "spawn_subagent",
                {
                    "subagent_type": subagent_type,
                    "description": description,
                },
            )
