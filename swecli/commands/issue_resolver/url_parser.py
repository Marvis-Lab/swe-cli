"""GitHub URL parsing utilities for issue resolver."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class GitHubIssueInfo:
    """Parsed GitHub issue information."""

    owner: str
    repo: str
    issue_number: int

    @property
    def repo_url(self) -> str:
        """Get the repository clone URL."""
        return f"https://github.com/{self.owner}/{self.repo}.git"

    @property
    def issue_url(self) -> str:
        """Get the full issue URL."""
        return f"https://github.com/{self.owner}/{self.repo}/issues/{self.issue_number}"

    @property
    def repo_full_name(self) -> str:
        """Get owner/repo format."""
        return f"{self.owner}/{self.repo}"


# Pattern for full GitHub issue URL
_FULL_URL_PATTERN = re.compile(
    r"(?:https?://)?github\.com/([^/]+)/([^/]+)/issues/(\d+)",
    re.IGNORECASE,
)

# Pattern for shorthand format: owner/repo#123
_SHORTHAND_PATTERN = re.compile(r"^([^/\s]+)/([^#\s]+)#(\d+)$")

# Pattern for just issue number in current repo context
_ISSUE_NUMBER_PATTERN = re.compile(r"^#?(\d+)$")


def parse_github_issue_url(url: str) -> Optional[GitHubIssueInfo]:
    """Parse a GitHub issue URL into components.

    Supports formats:
    - https://github.com/owner/repo/issues/123
    - github.com/owner/repo/issues/123
    - owner/repo#123

    Args:
        url: GitHub issue URL or shorthand

    Returns:
        GitHubIssueInfo or None if parsing fails
    """
    url = url.strip()

    # Try full URL pattern first
    match = _FULL_URL_PATTERN.match(url)
    if match:
        return GitHubIssueInfo(
            owner=match.group(1),
            repo=match.group(2),
            issue_number=int(match.group(3)),
        )

    # Try shorthand pattern
    match = _SHORTHAND_PATTERN.match(url)
    if match:
        return GitHubIssueInfo(
            owner=match.group(1),
            repo=match.group(2),
            issue_number=int(match.group(3)),
        )

    return None


def parse_issue_number(text: str) -> Optional[int]:
    """Parse just an issue number from text.

    Supports:
    - 123
    - #123

    Args:
        text: Text containing issue number

    Returns:
        Issue number or None
    """
    text = text.strip()
    match = _ISSUE_NUMBER_PATTERN.match(text)
    if match:
        return int(match.group(1))
    return None


def is_valid_github_issue_url(url: str) -> bool:
    """Check if a string is a valid GitHub issue URL.

    Args:
        url: String to validate

    Returns:
        True if valid GitHub issue URL
    """
    return parse_github_issue_url(url) is not None
