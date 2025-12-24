"""Command handler for /resolve-issue command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from swecli.commands.issue_resolver.mcp_github import MCPGitHub
from swecli.commands.issue_resolver.url_parser import parse_github_issue_url

if TYPE_CHECKING:
    from swecli.core.agents.subagents.manager import SubAgentManager
    from swecli.core.context_engineering.mcp.manager import MCPManager


@dataclass
class IssueResolverArgs:
    """Arguments for /resolve-issue command."""

    # GitHub mode
    issue_url: Optional[str] = None

    # SWE-bench mode
    dataset: Optional[str] = None  # "swebench-verified", "swebench-lite", "swebench-full"
    instance: Optional[str] = None  # Optional: specific instance ID
    parallel: int = 1  # Number of concurrent instances for batch mode

    # Common options
    skip_tests: bool = False
    auto_pr: bool = True

    @property
    def is_swebench_mode(self) -> bool:
        """Check if running in SWE-bench evaluation mode."""
        return self.dataset is not None and self.dataset.startswith("swebench-")

    @property
    def is_batch_mode(self) -> bool:
        """Check if running in batch mode (whole dataset)."""
        return self.is_swebench_mode and self.instance is None


@dataclass
class ResolveResult:
    """Result of issue resolution."""

    success: bool
    message: str
    repo_path: Optional[Path] = None
    branch: Optional[str] = None
    pr_url: Optional[str] = None
    patch: Optional[str] = None
    prediction_path: Optional[Path] = None


class IssueResolverCommand:
    """Thin wrapper that spawns Issue-Resolver subagent.

    The subagent handles the complete workflow:
    1. Clone repository
    2. Create fix branch
    3. Analyze and fix the issue
    4. Commit changes

    All progress is shown via the standard UI callback with ⏺ and ⎿ symbols.
    """

    def __init__(
        self,
        subagent_manager: "SubAgentManager",
        mcp_manager: "MCPManager",
        working_dir: Optional[Path] = None,
        mode_manager: Optional[Any] = None,
        approval_manager: Optional[Any] = None,
        undo_manager: Optional[Any] = None,
        ui_callback: Optional[Any] = None,
    ):
        """Initialize issue resolver command.

        Args:
            subagent_manager: SubAgentManager for spawning Issue-Resolver
            mcp_manager: MCP manager for GitHub operations
            working_dir: Working directory for operations
            mode_manager: Mode manager for subagent deps
            approval_manager: Approval manager for subagent deps
            undo_manager: Undo manager for subagent deps
            ui_callback: UI callback for displaying progress
        """
        self.subagent_manager = subagent_manager
        self.mcp_github = MCPGitHub(mcp_manager)
        # Use current directory - repos will be cloned to ./swebench-repos/
        self.working_dir = working_dir or Path.cwd()
        self.mode_manager = mode_manager
        self.approval_manager = approval_manager
        self.undo_manager = undo_manager
        self.ui_callback = ui_callback

    def parse_args(self, command: str) -> IssueResolverArgs:
        """Parse /resolve-issue command arguments.

        Args:
            command: Full command string

        Returns:
            Parsed arguments

        Raises:
            ValueError: If arguments are missing or invalid
        """
        from .swebench_loader import VALID_DATASETS

        parts = command.strip().split()

        # Common options
        skip_tests = "--skip-tests" in parts
        auto_pr = "--no-pr" not in parts

        # Check for --dataset flag (SWE-bench evaluation mode)
        if "--dataset" in parts:
            idx = parts.index("--dataset")
            if idx + 1 >= len(parts):
                raise ValueError("--dataset requires a value")
            dataset = parts[idx + 1]

            if dataset not in VALID_DATASETS:
                raise ValueError(
                    f"Invalid dataset '{dataset}'. "
                    f"Must be one of: {', '.join(VALID_DATASETS)}"
                )

            # Optional --instance (if not provided, runs whole dataset)
            instance = None
            if "--instance" in parts:
                i_idx = parts.index("--instance")
                if i_idx + 1 < len(parts):
                    instance = parts[i_idx + 1]

            # Optional --parallel (for batch mode)
            parallel = 1
            if "--parallel" in parts:
                p_idx = parts.index("--parallel")
                if p_idx + 1 < len(parts):
                    try:
                        parallel = int(parts[p_idx + 1])
                        if parallel < 1:
                            raise ValueError("--parallel must be at least 1")
                    except ValueError:
                        raise ValueError("--parallel requires a positive integer")

            return IssueResolverArgs(
                dataset=dataset,
                instance=instance,
                parallel=parallel,
                skip_tests=skip_tests,
                auto_pr=auto_pr,
            )

        # GitHub mode (existing behavior)
        if len(parts) < 2:
            raise ValueError(
                "Usage:\n"
                "  /resolve-issue <github-issue-url>\n"
                "  /resolve-issue --dataset swebench-verified [--instance <id>] [--parallel N]"
            )

        url = parts[1]

        # Validate URL
        if not parse_github_issue_url(url):
            raise ValueError(f"Invalid GitHub issue URL: {url}")

        return IssueResolverArgs(
            issue_url=url,
            skip_tests=skip_tests,
            auto_pr=auto_pr,
        )

    def execute(self, args: IssueResolverArgs) -> ResolveResult:
        """Execute the issue resolution by spawning Issue-Resolver subagent.

        Args:
            args: Parsed command arguments

        Returns:
            ResolveResult with success status and details
        """
        if args.is_swebench_mode:
            if args.is_batch_mode:
                return self._execute_swebench_batch(args)
            else:
                return self._execute_swebench_single(args)
        else:
            return self._execute_github_mode(args)

    def _execute_github_mode(self, args: IssueResolverArgs) -> ResolveResult:
        """Execute in GitHub mode (arbitrary issue URL).

        Flow:
        1. Fetch issue details via GitHub MCP
        2. Clone repo and create fix branch
        3. Spawn subagent with working_dir set to the prepared repo
        4. Generate prediction files

        Args:
            args: Parsed command arguments with issue_url

        Returns:
            ResolveResult with success status and details
        """
        from swecli.core.agents.subagents.manager import SubAgentDeps

        from .repo_setup import setup_github_repo

        # 1. Parse URL
        issue_info = parse_github_issue_url(args.issue_url)
        if not issue_info:
            return ResolveResult(
                success=False, message="Failed to parse GitHub issue URL"
            )

        # 2. Ensure GitHub MCP is connected (for fetching issue details)
        connected, msg = self.mcp_github.ensure_connected()
        if not connected:
            return ResolveResult(
                success=False,
                message=f"GitHub MCP connection failed: {msg}. "
                "Make sure GITHUB_TOKEN environment variable is set.",
            )

        # 3. Fetch issue details via MCP
        issue = self.mcp_github.get_issue(
            issue_info.owner,
            issue_info.repo,
            issue_info.issue_number,
        )

        if not issue:
            return ResolveResult(
                success=False, message="Failed to fetch issue details"
            )

        # 4. Build paths
        repo_dir = self.working_dir / f"{issue_info.owner}-{issue_info.repo}-issue-{issue_info.issue_number}"
        repo_url = f"https://github.com/{issue_info.owner}/{issue_info.repo}.git"
        branch_name = f"fix/issue-{issue_info.issue_number}"

        # 5. Setup repo BEFORE spawning subagent
        if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
            self.ui_callback.on_progress_start(f"Setting up repository for issue #{issue_info.issue_number}")

        success, msg = setup_github_repo(repo_url, repo_dir, branch_name)
        if not success:
            if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                self.ui_callback.on_progress_complete(f"Failed: {msg}", success=False)
            return ResolveResult(
                success=False,
                message=f"Repo setup failed: {msg}",
                repo_path=repo_dir,
            )

        if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
            self.ui_callback.on_progress_complete(f"Ready at {repo_dir}")

        # 6. Build task (NO clone instructions - repo already ready)
        task = self._build_github_task(issue, issue_info, repo_dir, branch_name)

        # 7. Create dependencies for subagent
        deps = SubAgentDeps(
            mode_manager=self.mode_manager,
            approval_manager=self.approval_manager,
            undo_manager=self.undo_manager,
        )

        # 8. Execute subagent IN THE PREPARED REPO
        try:
            result = self.subagent_manager.execute_subagent(
                name="Issue-Resolver",
                task=task,
                deps=deps,
                ui_callback=self.ui_callback,
                working_dir=repo_dir,  # Override working_dir to the prepared repo
            )
        except Exception as e:
            return ResolveResult(
                success=False,
                message=f"Subagent failed: {str(e)}",
                repo_path=repo_dir,
                branch=branch_name,
            )

        if not result.get("success"):
            return ResolveResult(
                success=False,
                message=f"Subagent failed: {result.get('error', 'Unknown error')}",
                repo_path=repo_dir,
                branch=branch_name,
            )

        # 9. Generate SWE-bench compatible prediction files
        patch, pred_path = self._generate_prediction_github(issue_info, repo_dir)

        return ResolveResult(
            success=True,
            message="Issue resolved successfully",
            repo_path=repo_dir,
            branch=branch_name,
            patch=patch,
            prediction_path=pred_path,
        )

    def _execute_swebench_single(self, args: IssueResolverArgs) -> ResolveResult:
        """Execute in SWE-bench single instance mode.

        Flow:
        1. Load instance from HuggingFace dataset (auto-downloads if needed)
        2. Clone repo and checkout base_commit
        3. Spawn subagent with working_dir set to the prepared repo
        4. Generate prediction files

        Args:
            args: Parsed command arguments with dataset and instance

        Returns:
            ResolveResult with success status and details
        """
        from swecli.core.agents.subagents.manager import SubAgentDeps

        from .repo_setup import setup_swebench_repo
        from .swebench_loader import load_swebench_instance

        # Step 1: Load dataset and check instance (auto-downloads if needed)
        if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
            self.ui_callback.on_progress_start(f"Loading {args.dataset} dataset")

        try:
            instance = load_swebench_instance(
                args.instance,
                args.dataset,
            )
        except ImportError as e:
            if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                self.ui_callback.on_progress_complete(str(e), success=False)
            return ResolveResult(
                success=False,
                message=str(e),
            )
        except ValueError as e:
            if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                self.ui_callback.on_progress_complete(str(e), success=False)
            return ResolveResult(
                success=False,
                message=str(e),
            )

        if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
            self.ui_callback.on_progress_complete(
                f"Loaded {instance.instance_id} ({instance.repo} @ {instance.base_commit[:7]})"
            )

        # Step 2: Build paths - use repo_name as subdirectory (e.g., ./astropy)
        repo_name = instance.repo.split("/")[-1]  # "astropy" from "astropy/astropy"
        repo_dir = self.working_dir / repo_name
        repo_url = f"https://github.com/{instance.repo}.git"
        branch_name = f"fix/{instance.instance_id}"

        # Step 3: Setup repo BEFORE spawning subagent
        if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
            self.ui_callback.on_progress_start(f"Cloning {instance.repo}")

        success, msg = setup_swebench_repo(repo_url, repo_dir, instance.base_commit, branch_name)
        if not success:
            if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                self.ui_callback.on_progress_complete(f"Failed: {msg}", success=False)
            return ResolveResult(
                success=False,
                message=f"Repo setup failed: {msg}",
                repo_path=repo_dir,
            )

        if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
            self.ui_callback.on_progress_complete(f"Ready at {repo_dir}")

        # 4. Build task (NO clone instructions - repo already ready)
        task = self._build_swebench_task(instance, repo_dir, branch_name)

        # 5. Create dependencies for subagent
        deps = SubAgentDeps(
            mode_manager=self.mode_manager,
            approval_manager=self.approval_manager,
            undo_manager=self.undo_manager,
        )

        # 6. Execute subagent IN THE PREPARED REPO
        try:
            result = self.subagent_manager.execute_subagent(
                name="Issue-Resolver",
                task=task,
                deps=deps,
                ui_callback=self.ui_callback,
                working_dir=repo_dir,  # Override working_dir to the prepared repo
            )
        except Exception as e:
            return ResolveResult(
                success=False,
                message=f"Subagent failed: {str(e)}",
                repo_path=repo_dir,
                branch=branch_name,
            )

        # Handle string result (can happen if agent returns plain text)
        if isinstance(result, str):
            return ResolveResult(
                success=True,
                message=result,
                repo_path=repo_dir,
                branch=branch_name,
            )

        if not result.get("success"):
            return ResolveResult(
                success=False,
                message=f"Subagent failed: {result.get('error', 'Unknown error')}",
                repo_path=repo_dir,
                branch=branch_name,
            )

        # 7. Generate SWE-bench compatible prediction files
        patch, pred_path = self._generate_prediction_swebench(instance, args.dataset, repo_dir)

        return ResolveResult(
            success=True,
            message=f"SWE-bench instance {instance.instance_id} resolved successfully",
            repo_path=repo_dir,
            branch=branch_name,
            patch=patch,
            prediction_path=pred_path,
        )

    def _execute_swebench_batch(self, args: IssueResolverArgs) -> ResolveResult:
        """Execute in SWE-bench batch mode (whole dataset).

        Runs all instances in the dataset, with auto-skip for completed ones
        and optional parallel execution.

        Args:
            args: Parsed command arguments with dataset and parallel

        Returns:
            ResolveResult with batch completion status
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from .swebench_loader import get_all_instance_ids

        # Get all instance IDs
        try:
            all_instances = get_all_instance_ids(args.dataset)
        except (ImportError, ValueError) as e:
            return ResolveResult(success=False, message=str(e))

        # Filter out completed instances (auto-skip)
        predictions_dir = self.working_dir / "swebench-benchmarks" / args.dataset
        pending = [
            inst for inst in all_instances
            if not (predictions_dir / f"{inst}.pred").exists()
        ]

        total = len(all_instances)
        skipped = total - len(pending)

        if not pending:
            return ResolveResult(
                success=True,
                message=f"All {total} instances already completed. Nothing to do.",
            )

        # Log progress
        if self.ui_callback and hasattr(self.ui_callback, "on_message"):
            msg = f"Starting batch: {len(pending)} pending, {skipped} skipped (already completed)"
            self.ui_callback.on_message(msg)

        # Execute instances
        if args.parallel > 1:
            return self._execute_batch_parallel(pending, args, total)
        else:
            return self._execute_batch_sequential(pending, args, total)

    def _execute_batch_sequential(
        self, instances: list[str], args: IssueResolverArgs, total: int
    ) -> ResolveResult:
        """Execute instances sequentially."""
        succeeded = 0
        failed = 0

        for i, instance_id in enumerate(instances, 1):
            if self.ui_callback and hasattr(self.ui_callback, "on_message"):
                self.ui_callback.on_message(f"[{i}/{len(instances)}] Resolving {instance_id}...")

            # Create args for single instance
            single_args = IssueResolverArgs(
                dataset=args.dataset,
                instance=instance_id,
                skip_tests=args.skip_tests,
                auto_pr=args.auto_pr,
            )

            result = self._execute_swebench_single(single_args)
            if result.success:
                succeeded += 1
            else:
                failed += 1

        return ResolveResult(
            success=True,
            message=f"Batch complete: {succeeded} resolved, {failed} failed out of {total} total",
        )

    def _execute_batch_parallel(
        self, instances: list[str], args: IssueResolverArgs, total: int
    ) -> ResolveResult:
        """Execute instances in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        succeeded = 0
        failed = 0

        def resolve_instance(instance_id: str) -> tuple[str, bool]:
            single_args = IssueResolverArgs(
                dataset=args.dataset,
                instance=instance_id,
                skip_tests=args.skip_tests,
                auto_pr=args.auto_pr,
            )
            result = self._execute_swebench_single(single_args)
            return instance_id, result.success

        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = {
                executor.submit(resolve_instance, inst): inst
                for inst in instances
            }

            for i, future in enumerate(as_completed(futures), 1):
                instance_id = futures[future]
                try:
                    _, success = future.result()
                    if success:
                        succeeded += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

                if self.ui_callback and hasattr(self.ui_callback, "on_message"):
                    self.ui_callback.on_message(
                        f"[{i}/{len(instances)}] Completed {instance_id} "
                        f"({succeeded} ok, {failed} failed)"
                    )

        return ResolveResult(
            success=True,
            message=f"Batch complete: {succeeded} resolved, {failed} failed out of {total} total",
        )

    def _build_github_task(
        self, issue: Any, issue_info: Any, repo_dir: Path, branch_name: str
    ) -> str:
        """Build task description for GitHub mode.

        The repo is already cloned and checked out on the fix branch.
        """
        labels_text = ", ".join(issue.labels) if issue.labels else "None"

        return f"""Resolve GitHub issue #{issue_info.issue_number} from {issue_info.owner}/{issue_info.repo}

## Issue Details

**Title:** {issue.title}

**Author:** {issue.author}

**Labels:** {labels_text}

**Description:**
{issue.body}

## Your Task

You are already in the repository at `{repo_dir}` on branch `{branch_name}`.

1. Analyze the issue and explore the codebase using `search` and `read_file`
2. Make the necessary code changes using `edit_file`
3. Commit your changes:
   ```bash
   git add -A
   git commit -m "fix: {issue.title}"
   ```
4. Provide a summary of what was fixed

## Important Notes

- Make minimal, focused changes
- Follow the existing code style
- Commit your changes before finishing
"""

    def _build_swebench_task(
        self, instance: Any, repo_dir: Path, branch_name: str
    ) -> str:
        """Build task description for SWE-bench evaluation mode.

        The repo is already cloned and checked out at base_commit.
        """
        return f"""Resolve SWE-bench instance: {instance.instance_id}

## Problem Statement

{instance.problem_statement}

## Repository Location

The repository has been cloned to `{repo_dir}` and checked out at commit `{instance.base_commit}` on branch `{branch_name}`.

**IMPORTANT**: Use absolute paths for all file operations. For example:
- `read_file("{repo_dir}/path/to/file.py")`
- `edit_file("{repo_dir}/path/to/file.py", ...)`
- `search("{repo_dir}", ...)`

For git commands, cd into the repo first:
- `cd {repo_dir} && git add -A && git commit -m "fix: ..."`

## Your Task

1. Analyze the problem statement carefully
2. Explore the codebase using `search` and `read_file` to understand the issue
3. Implement the fix using `edit_file`
4. Commit your changes:
   ```bash
   cd {repo_dir} && git add -A && git commit -m "fix: {instance.instance_id}"
   ```
5. Provide a summary of what was fixed

## Important Notes

- Make minimal, focused changes
- Follow the existing code style
- Commit your changes before finishing
"""

    def _generate_prediction_github(
        self, issue_info: Any, repo_dir: Path
    ) -> tuple[str, Optional[Path]]:
        """Generate SWE-bench compatible prediction files for GitHub mode.

        Args:
            issue_info: Parsed issue information
            repo_dir: Path to the cloned repository

        Returns:
            Tuple of (patch_content, prediction_file_path)
        """
        from .patch_extractor import extract_patch, get_base_branch
        from .prediction import Prediction, generate_instance_id, save_prediction

        # Extract patch from committed changes
        base_branch = get_base_branch(repo_dir)
        patch = extract_patch(repo_dir, base_branch)

        # Generate instance ID in SWE-bench format
        instance_id = generate_instance_id(
            issue_info.owner, issue_info.repo, issue_info.issue_number
        )

        # Create and save prediction (GitHub mode saves to swebench-benchmarks/github/)
        pred = Prediction(
            instance_id=instance_id,
            model_patch=patch if patch.strip() else None,
        )
        predictions_dir = self.working_dir / "swebench-benchmarks" / "github"
        pred_path, _ = save_prediction(pred, predictions_dir)

        return patch, pred_path

    def _generate_prediction_swebench(
        self, instance: Any, dataset: str, repo_dir: Path
    ) -> tuple[str, Optional[Path]]:
        """Generate SWE-bench compatible prediction files for SWE-bench mode.

        Args:
            instance: SWEBenchInstance from the dataset
            dataset: Dataset name (e.g., "swebench-verified")
            repo_dir: Path to the cloned repository

        Returns:
            Tuple of (patch_content, prediction_file_path)
        """
        from .patch_extractor import extract_patch
        from .prediction import Prediction, save_prediction

        # Extract patch from committed changes (diff from base_commit)
        patch = extract_patch(repo_dir, instance.base_commit)

        # Use instance_id directly from the dataset
        pred = Prediction(
            instance_id=instance.instance_id,
            model_patch=patch if patch.strip() else None,
        )
        # Save to swebench-benchmarks/{dataset}/ folder
        predictions_dir = self.working_dir / "swebench-benchmarks" / dataset
        pred_path, _ = save_prediction(pred, predictions_dir)

        return patch, pred_path
