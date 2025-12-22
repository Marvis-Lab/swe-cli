"""Command handler for /resolve-issue command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rich.console import Console
from rich.panel import Panel

from swecli.commands.issue_resolver.github_helper import GitHelper
from swecli.commands.issue_resolver.mcp_github import MCPGitHub, GitHubIssue
from swecli.commands.issue_resolver.url_parser import (
    GitHubIssueInfo,
    parse_github_issue_url,
)

if TYPE_CHECKING:
    from swecli.core.agents.subagents.manager import SubAgentManager
    from swecli.core.context_engineering.mcp.manager import MCPManager


@dataclass
class IssueResolverArgs:
    """Arguments for /resolve-issue command."""

    issue_url: str
    skip_tests: bool = False
    auto_pr: bool = True


@dataclass
class ResolveResult:
    """Result of issue resolution."""

    success: bool
    message: str
    repo_path: Optional[Path] = None
    branch: Optional[str] = None
    pr_url: Optional[str] = None
    resolution_summary: str = ""


class IssueResolverCommand:
    """Handler for /resolve-issue command.

    Orchestrates the full issue resolution workflow using hybrid approach:
    - MCP for GitHub API operations (fetch issue, fork, create PR)
    - Local git operations for clone, branch, commit, push

    Workflow:
    1. Parse GitHub issue URL
    2. Connect to GitHub MCP (auto-configure if needed)
    3. Fetch issue details via MCP
    4. Fork repository via MCP
    5. Clone fork locally
    6. Create fix branch
    7. Spawn Issue-Resolver subagent
    8. Run tests (optional)
    9. Commit and push changes
    10. Create PR via MCP
    """

    def __init__(
        self,
        console: Console,
        subagent_manager: "SubAgentManager",
        mcp_manager: "MCPManager",
        working_dir: Optional[Path] = None,
    ):
        """Initialize issue resolver command.

        Args:
            console: Rich console for output
            subagent_manager: SubAgentManager for spawning Issue-Resolver
            mcp_manager: MCP manager for GitHub operations
            working_dir: Working directory for operations
        """
        self.console = console
        self.subagent_manager = subagent_manager
        self.mcp_github = MCPGitHub(mcp_manager)
        self.git = GitHelper(working_dir)

    def parse_args(self, command: str) -> IssueResolverArgs:
        """Parse /resolve-issue command arguments.

        Args:
            command: Full command string

        Returns:
            Parsed arguments

        Raises:
            ValueError: If URL is missing or invalid
        """
        parts = command.strip().split()

        if len(parts) < 2:
            raise ValueError(
                "Usage: /resolve-issue <github-issue-url> [--skip-tests] [--no-pr]"
            )

        url = parts[1]
        skip_tests = "--skip-tests" in parts
        auto_pr = "--no-pr" not in parts

        # Validate URL
        if not parse_github_issue_url(url):
            raise ValueError(f"Invalid GitHub issue URL: {url}")

        return IssueResolverArgs(
            issue_url=url,
            skip_tests=skip_tests,
            auto_pr=auto_pr,
        )

    def execute(self, args: IssueResolverArgs) -> ResolveResult:
        """Execute the issue resolution workflow.

        Args:
            args: Parsed command arguments

        Returns:
            ResolveResult with success status and details
        """
        # Step 1: Parse URL
        issue_info = parse_github_issue_url(args.issue_url)
        if not issue_info:
            return ResolveResult(
                success=False, message="Failed to parse GitHub issue URL"
            )

        self.console.print(
            f"[cyan]Resolving issue: {issue_info.owner}/{issue_info.repo}#{issue_info.issue_number}[/cyan]"
        )

        # Step 2: Connect to GitHub MCP
        self.console.print("[dim]Connecting to GitHub MCP server...[/dim]")
        connected, msg = self.mcp_github.ensure_connected()
        if not connected:
            return ResolveResult(
                success=False,
                message=f"GitHub MCP connection failed: {msg}. "
                "Make sure GITHUB_TOKEN environment variable is set.",
            )
        self.console.print(f"[green]{msg}[/green]")

        # Step 3: Fetch issue details via MCP
        self.console.print("[dim]Fetching issue details...[/dim]")
        issue = self.mcp_github.get_issue(
            issue_info.owner,
            issue_info.repo,
            issue_info.issue_number,
        )

        if not issue:
            return ResolveResult(
                success=False, message="Failed to fetch issue details"
            )

        self._display_issue(issue)

        # Step 4: Fork repository via MCP
        self.console.print("[dim]Forking repository...[/dim]")
        fork_result = self.mcp_github.fork_repository(
            issue_info.owner,
            issue_info.repo,
        )

        if not fork_result.success:
            return ResolveResult(
                success=False,
                message=f"Fork failed: {fork_result.error}",
            )

        fork_owner = fork_result.fork_owner
        fork_clone_url = fork_result.clone_url
        self.console.print(f"[green]Forked to:[/green] {fork_owner}/{fork_result.fork_name}")

        # Step 5: Clone fork locally
        self.console.print("[dim]Cloning fork locally...[/dim]")
        clone_result = self.git.clone_repo(
            clone_url=fork_clone_url,
            owner=fork_owner,
            repo=issue_info.repo,
            issue_number=issue_info.issue_number,
        )

        if not clone_result.success:
            return ResolveResult(
                success=False, message=f"Clone failed: {clone_result.error}"
            )

        repo_path = clone_result.repo_path
        self.console.print(f"[green]Cloned to:[/green] {repo_path}")

        # Set up upstream remote (for reference)
        self.git.set_remote_url(
            repo_path,
            "upstream",
            f"https://github.com/{issue_info.owner}/{issue_info.repo}.git",
        )

        # Step 6: Create branch
        branch_name = f"fix/issue-{issue_info.issue_number}"
        if not self.git.create_branch(repo_path, branch_name):
            return ResolveResult(success=False, message="Failed to create branch")

        self.console.print(f"[dim]Created branch:[/dim] {branch_name}")

        # Step 7: Spawn Issue-Resolver subagent
        self.console.print("[cyan]Spawning Issue-Resolver subagent...[/cyan]")

        task_description = self._build_task_description(issue, repo_path)

        # Execute subagent with the cloned repo as working directory
        try:
            # Store original working dir
            original_working_dir = getattr(self.subagent_manager, "_working_dir", None)

            # Update working directory for subagent
            self.subagent_manager._working_dir = repo_path

            result = self.subagent_manager.execute_subagent(
                name="Issue-Resolver",
                task=task_description,
            )

            # Restore working directory
            if original_working_dir:
                self.subagent_manager._working_dir = original_working_dir

        except Exception as e:
            return ResolveResult(
                success=False,
                message=f"Subagent failed: {str(e)}",
                repo_path=repo_path,
                branch=branch_name,
            )

        if not result.get("success"):
            return ResolveResult(
                success=False,
                message=f"Subagent failed: {result.get('error', 'Unknown error')}",
                repo_path=repo_path,
                branch=branch_name,
            )

        resolution_summary = result.get("content", "")

        # Step 8: Check if there are changes
        if not self.git.has_changes(repo_path):
            return ResolveResult(
                success=False,
                message="No changes were made to resolve the issue",
                repo_path=repo_path,
                branch=branch_name,
            )

        # Show diff for confirmation
        self.console.print("\n[cyan]Changes made:[/cyan]")
        diff = self.git.get_diff(repo_path)
        if diff:
            # Truncate diff for display
            diff_lines = diff.split("\n")
            if len(diff_lines) > 50:
                diff_preview = "\n".join(diff_lines[:50])
                diff_preview += f"\n... ({len(diff_lines) - 50} more lines)"
            else:
                diff_preview = diff
            self.console.print(Panel(diff_preview, title="Diff", border_style="dim"))

        # Step 9: Run tests (optional)
        if not args.skip_tests:
            self._run_tests(repo_path)

        # Step 10: Commit changes
        commit_message = f"fix: resolve issue #{issue_info.issue_number}\n\n{issue.title}"
        if not self.git.commit_changes(repo_path, commit_message):
            return ResolveResult(
                success=False,
                message="Failed to commit changes",
                repo_path=repo_path,
                branch=branch_name,
            )

        self.console.print("[green]Changes committed[/green]")

        # Step 11: Push to fork
        self.console.print("[dim]Pushing to fork...[/dim]")
        push_success, push_error = self.git.push_branch(repo_path)
        if not push_success:
            return ResolveResult(
                success=False,
                message=f"Push failed: {push_error}",
                repo_path=repo_path,
                branch=branch_name,
            )
        self.console.print("[green]Pushed to fork[/green]")

        # Step 12: Create PR via MCP (optional)
        pr_url = None
        if args.auto_pr:
            pr_url = self._create_pr(
                issue_info,
                issue,
                fork_owner,
                branch_name,
                resolution_summary,
            )

        return ResolveResult(
            success=True,
            message="Issue resolved successfully",
            repo_path=repo_path,
            branch=branch_name,
            pr_url=pr_url,
            resolution_summary=resolution_summary,
        )

    def _display_issue(self, issue: GitHubIssue) -> None:
        """Display issue details in a panel."""
        labels_text = ", ".join(issue.labels) if issue.labels else "None"

        content = f"[bold]{issue.title}[/bold]\n\n"
        content += f"[dim]Author:[/dim] {issue.author}\n"
        content += f"[dim]Labels:[/dim] {labels_text}\n"
        content += f"[dim]State:[/dim] {issue.state}"

        self.console.print(Panel(content, title=f"Issue #{issue.number}", border_style="green"))

    def _build_task_description(self, issue: GitHubIssue, repo_path: Path) -> str:
        """Build detailed task description for Issue-Resolver subagent."""
        labels_text = ", ".join(issue.labels) if issue.labels else "None"

        return f"""Resolve the following GitHub issue in the repository at {repo_path}:

## Issue #{issue.number}: {issue.title}

{issue.body}

## Labels
{labels_text}

## Your Task

1. Analyze the issue to understand what needs to be fixed
2. Explore the codebase to find relevant files
3. Make the necessary code changes to resolve the issue
4. Ensure your changes are minimal and focused on the issue
5. Add any necessary tests if appropriate
6. Provide a summary of changes made

Focus on making clean, production-ready changes that follow the existing code patterns and style.

Remember: The repository is already cloned at {repo_path} - you can start exploring and making changes immediately.
"""

    def _run_tests(self, repo_path: Path) -> None:
        """Run tests and display results."""
        self.console.print("[dim]Running tests...[/dim]")
        test_result = self.git.run_tests(repo_path)

        if test_result.success is None:
            self.console.print("[yellow]Warning: No test runner detected[/yellow]")
        elif not test_result.success:
            self.console.print(
                f"[yellow]Warning: Tests failed ({test_result.command})[/yellow]"
            )
            if test_result.stderr:
                # Show truncated error output
                error_preview = test_result.stderr[:500]
                if len(test_result.stderr) > 500:
                    error_preview += "..."
                self.console.print(f"[dim]{error_preview}[/dim]")
            self.console.print("[dim]Proceeding anyway as requested...[/dim]")
        else:
            self.console.print(f"[green]Tests passed ({test_result.command})[/green]")

    def _create_pr(
        self,
        issue_info: GitHubIssueInfo,
        issue: GitHubIssue,
        fork_owner: str,
        branch_name: str,
        resolution_summary: str,
    ) -> Optional[str]:
        """Create a pull request via MCP."""
        self.console.print("[dim]Creating pull request...[/dim]")

        pr_body = self._build_pr_body(issue, resolution_summary)

        # For cross-fork PRs, head should be 'fork_owner:branch_name'
        head = f"{fork_owner}:{branch_name}"

        pr_result = self.mcp_github.create_pull_request(
            owner=issue_info.owner,
            repo=issue_info.repo,
            title=f"Fix #{issue_info.issue_number}: {issue.title}",
            body=pr_body,
            head=head,
            base="main",  # TODO: detect default branch
        )

        if pr_result.success and pr_result.url:
            self.console.print(f"[green]PR created:[/green] {pr_result.url}")
            return pr_result.url
        else:
            self.console.print(
                f"[yellow]Warning: Failed to create PR: {pr_result.error}[/yellow]"
            )
            return None

    def _build_pr_body(self, issue: GitHubIssue, resolution_summary: str) -> str:
        """Build PR body with resolution summary."""
        return f"""## Summary

Resolves #{issue.number}

## Changes Made

{resolution_summary if resolution_summary else "_Resolution summary not available_"}

## Test Plan

- [ ] Existing tests pass
- [ ] Changes reviewed for correctness
- [ ] No unintended side effects

---
Generated by SWE-CLI Issue Resolver
"""
