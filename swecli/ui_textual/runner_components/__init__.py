"""Runner components for TextualRunner refactoring.

This package contains extracted components from the monolithic TextualRunner
class, following the Single Responsibility Principle.
"""

from swecli.ui_textual.runner_components.history_hydrator import HistoryHydrator
from swecli.ui_textual.runner_components.tool_renderer import ToolRenderer
from swecli.ui_textual.runner_components.model_config_manager import ModelConfigManager
from swecli.ui_textual.runner_components.command_router import CommandRouter
from swecli.ui_textual.runner_components.message_processor import MessageProcessor

__all__ = [
    "HistoryHydrator",
    "ToolRenderer",
    "ModelConfigManager",
    "CommandRouter",
    "MessageProcessor",
]
