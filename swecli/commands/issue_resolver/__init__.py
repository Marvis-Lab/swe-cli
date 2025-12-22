"""GitHub Issue Resolver command module."""

from swecli.commands.issue_resolver.command import (
    IssueResolverArgs,
    IssueResolverCommand,
    ResolveResult,
)
from swecli.commands.issue_resolver.github_helper import (
    CloneResult,
    GitHelper,
    TestResult,
)
from swecli.commands.issue_resolver.mcp_github import (
    ForkResult,
    GitHubIssue,
    MCPGitHub,
    PRResult,
)
from swecli.commands.issue_resolver.url_parser import (
    GitHubIssueInfo,
    is_valid_github_issue_url,
    parse_github_issue_url,
    parse_issue_number,
)

__all__ = [
    # Command
    "IssueResolverArgs",
    "IssueResolverCommand",
    "ResolveResult",
    # Git Helper (local git operations)
    "CloneResult",
    "GitHelper",
    "TestResult",
    # MCP GitHub (GitHub API via MCP)
    "ForkResult",
    "GitHubIssue",
    "MCPGitHub",
    "PRResult",
    # URL Parser
    "GitHubIssueInfo",
    "is_valid_github_issue_url",
    "parse_github_issue_url",
    "parse_issue_number",
]
