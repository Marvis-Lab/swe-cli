"""MCP GitHub wrapper for issue resolver."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from swecli.core.context_engineering.mcp.manager import MCPManager


# GitHub MCP server configuration
GITHUB_MCP_SERVER_NAME = "github"
GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp"


@dataclass
class GitHubIssue:
    """GitHub issue details."""

    number: int
    title: str
    body: str
    labels: list[str]
    state: str
    author: str
    url: str
    repo_owner: str
    repo_name: str


@dataclass
class ForkResult:
    """Result of fork operation."""

    success: bool
    fork_owner: Optional[str] = None
    fork_name: Optional[str] = None
    clone_url: Optional[str] = None
    error: Optional[str] = None


@dataclass
class PRResult:
    """Result of PR creation."""

    success: bool
    url: Optional[str] = None
    number: Optional[int] = None
    error: Optional[str] = None


class MCPGitHub:
    """Wrapper for GitHub MCP server operations."""

    def __init__(self, mcp_manager: "MCPManager"):
        """Initialize MCP GitHub helper.

        Args:
            mcp_manager: MCP manager instance
        """
        self.mcp = mcp_manager

    def ensure_connected(self) -> tuple[bool, str]:
        """Ensure GitHub MCP server is configured and connected.

        Auto-configures the server if not present using HTTP transport.

        Returns:
            Tuple of (success, message)
        """
        # Check if already connected
        if self.mcp.is_connected(GITHUB_MCP_SERVER_NAME):
            return True, "GitHub MCP server connected"

        # Check if configured
        config = self.mcp.get_config()
        if GITHUB_MCP_SERVER_NAME not in config.mcp_servers:
            # Auto-configure GitHub MCP server using HTTP transport
            self.mcp.add_server(
                name=GITHUB_MCP_SERVER_NAME,
                transport="http",
                url=GITHUB_MCP_URL,
                headers={"Authorization": "Bearer ${GITHUB_TOKEN}"},
            )

        # Try to connect
        try:
            success = self.mcp.connect_sync(GITHUB_MCP_SERVER_NAME)
            if success:
                return True, "GitHub MCP server connected"
            return False, "Failed to connect to GitHub MCP server"
        except Exception as e:
            return False, f"Connection error: {e}"

    def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a GitHub MCP tool.

        Args:
            tool_name: Name of the tool (without server prefix)
            arguments: Tool arguments

        Returns:
            Tool result dict with 'success' and 'output' or 'error'
        """
        return self.mcp.call_tool_sync(GITHUB_MCP_SERVER_NAME, tool_name, arguments)

    def get_issue(
        self, owner: str, repo: str, issue_number: int
    ) -> Optional[GitHubIssue]:
        """Fetch issue details via MCP.

        Args:
            owner: Repository owner
            repo: Repository name
            issue_number: Issue number

        Returns:
            GitHubIssue or None if fetch fails
        """
        result = self._call_tool(
            "issue_read",
            {
                "method": "get",
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
            },
        )

        if not result.get("success"):
            return None

        try:
            # Parse the output - GitHub MCP returns JSON
            output = result.get("output", "")
            if isinstance(output, str):
                data = json.loads(output)
            else:
                data = output

            return GitHubIssue(
                number=data.get("number", issue_number),
                title=data.get("title", ""),
                body=data.get("body", "") or "",
                labels=[
                    label.get("name", "") if isinstance(label, dict) else str(label)
                    for label in data.get("labels", [])
                ],
                state=data.get("state", "open"),
                author=data.get("user", {}).get("login", "unknown")
                if isinstance(data.get("user"), dict)
                else "unknown",
                url=data.get("html_url", f"https://github.com/{owner}/{repo}/issues/{issue_number}"),
                repo_owner=owner,
                repo_name=repo,
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def fork_repository(self, owner: str, repo: str) -> ForkResult:
        """Fork a repository via MCP.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            ForkResult with fork details
        """
        result = self._call_tool(
            "fork_repository",
            {
                "owner": owner,
                "repo": repo,
            },
        )

        if not result.get("success"):
            return ForkResult(
                success=False,
                error=result.get("error", "Fork failed"),
            )

        try:
            output = result.get("output", "")
            if isinstance(output, str):
                data = json.loads(output)
            else:
                data = output

            return ForkResult(
                success=True,
                fork_owner=data.get("owner", {}).get("login", ""),
                fork_name=data.get("name", repo),
                clone_url=data.get("clone_url", ""),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return ForkResult(success=False, error=f"Parse error: {e}")

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> PRResult:
        """Create a pull request via MCP.

        Args:
            owner: Target repository owner
            repo: Target repository name
            title: PR title
            body: PR body
            head: Head branch (format: 'username:branch' for cross-fork PRs)
            base: Base branch (default: main)

        Returns:
            PRResult with PR URL if successful
        """
        result = self._call_tool(
            "create_pull_request",
            {
                "owner": owner,
                "repo": repo,
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            },
        )

        if not result.get("success"):
            return PRResult(
                success=False,
                error=result.get("error", "PR creation failed"),
            )

        try:
            output = result.get("output", "")
            if isinstance(output, str):
                data = json.loads(output)
            else:
                data = output

            return PRResult(
                success=True,
                url=data.get("html_url", ""),
                number=data.get("number"),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return PRResult(success=False, error=f"Parse error: {e}")

    def get_repository(self, owner: str, repo: str) -> Optional[dict[str, Any]]:
        """Get repository details via MCP.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            Repository data dict or None
        """
        result = self._call_tool(
            "get_repository",
            {
                "owner": owner,
                "repo": repo,
            },
        )

        if not result.get("success"):
            return None

        try:
            output = result.get("output", "")
            if isinstance(output, str):
                return json.loads(output)
            return output
        except json.JSONDecodeError:
            return None

    def get_authenticated_user(self) -> Optional[str]:
        """Get the authenticated user's login.

        Returns:
            Username or None if not authenticated
        """
        result = self._call_tool("get_me", {})

        if not result.get("success"):
            return None

        try:
            output = result.get("output", "")
            if isinstance(output, str):
                data = json.loads(output)
            else:
                data = output
            return data.get("login")
        except (json.JSONDecodeError, KeyError, TypeError):
            return None
