"""Subagent specifications."""

from .ask_user import ASK_USER_SUBAGENT
from .code_explorer import CODE_EXPLORER_SUBAGENT
from .init_agent import INIT_SUBAGENT
from .planner import PLANNER_SUBAGENT
from .web_clone import WEB_CLONE_SUBAGENT
from .web_generator import WEB_GENERATOR_SUBAGENT

ALL_SUBAGENTS = [
    ASK_USER_SUBAGENT,
    CODE_EXPLORER_SUBAGENT,
    INIT_SUBAGENT,
    PLANNER_SUBAGENT,
    WEB_CLONE_SUBAGENT,
    WEB_GENERATOR_SUBAGENT,
]
