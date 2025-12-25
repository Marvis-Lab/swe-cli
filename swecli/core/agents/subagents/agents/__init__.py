"""Subagent specifications."""

from .code_explorer import CODE_EXPLORER_SUBAGENT
from .web_clone import WEB_CLONE_SUBAGENT
from .web_generator import WEB_GENERATOR_SUBAGENT
from .code_reviewer import CODE_REVIEWER_SUBAGENT
from .test_writer import TEST_WRITER_SUBAGENT
from .documentation import DOCUMENTATION_SUBAGENT
from .paper2code import PAPER2CODE_SUBAGENT
from .issue_resolver import ISSUE_RESOLVER_SUBAGENT
from .github_resolver import GITHUB_RESOLVER_SUBAGENT

ALL_SUBAGENTS = [
    CODE_EXPLORER_SUBAGENT,
    WEB_CLONE_SUBAGENT,
    WEB_GENERATOR_SUBAGENT,
    CODE_REVIEWER_SUBAGENT,
    TEST_WRITER_SUBAGENT,
    DOCUMENTATION_SUBAGENT,
    PAPER2CODE_SUBAGENT,
    ISSUE_RESOLVER_SUBAGENT,
    GITHUB_RESOLVER_SUBAGENT,
]
