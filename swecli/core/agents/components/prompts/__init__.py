"""System prompt construction for SWE-CLI agents.

This subpackage contains prompt builders for different agent modes:
- SystemPromptBuilder: NORMAL mode with full tool access
- PlanningPromptBuilder: PLAN mode for strategic planning
- ThinkingPromptBuilder: THINKING mode for step-by-step reasoning
"""

from .builders import PlanningPromptBuilder, SystemPromptBuilder, ThinkingPromptBuilder
from .environment import EnvironmentCollector, EnvironmentContext

__all__ = [
    "EnvironmentCollector",
    "EnvironmentContext",
    "PlanningPromptBuilder",
    "SystemPromptBuilder",
    "ThinkingPromptBuilder",
]
