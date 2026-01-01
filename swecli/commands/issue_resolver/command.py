"""Command handler for /resolve-issue command.

Supports two modes:
- SWE-bench: Evaluation using pre-built Docker images from HuggingFace datasets
- GitHub: Real GitHub issues resolved in Docker containers
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

if TYPE_CHECKING:
    from swecli.core.agents.subagents.manager import SubAgentManager
    from swecli.core.context_engineering.mcp.manager import MCPManager


@dataclass
class IssueResolverArgs:
    """Arguments for /resolve-issue command."""

    # Mode detection (swebench or github)
    mode: Literal["swebench", "github"] = "swebench"

    # SWE-bench mode
    dataset: Optional[str] = None  # "swebench-verified", "swebench-lite", "swebench-full"
    instance: Optional[str] = None  # Optional: specific instance ID
    parallel: int = 1  # Number of concurrent instances for batch mode

    # GitHub mode
    issue_url: Optional[str] = None  # Full GitHub issue URL

    # Docker configuration
    docker_memory: str = "4g"
    docker_cpus: str = "4"

    @property
    def is_batch_mode(self) -> bool:
        """Check if running in batch mode (whole dataset)."""
        return self.mode == "swebench" and self.instance is None


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
    """Docker-based issue resolver for SWE-bench and GitHub issues.

    Supports two modes:
    - SWE-bench: Uses pre-built Docker images with repos at /testbed
    - GitHub: Clones repos into generic Docker containers at /workspace

    All progress is shown via the standard UI callback.
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
            subagent_manager: SubAgentManager for spawning subagents
            mcp_manager: MCP manager for GitHub API operations
            working_dir: Working directory for saving patches
            mode_manager: Mode manager for subagent deps
            approval_manager: Approval manager for subagent deps
            undo_manager: Undo manager for subagent deps
            ui_callback: UI callback for displaying progress
        """
        from .mcp_github import MCPGitHub

        self.subagent_manager = subagent_manager
        self.mcp_github = MCPGitHub(mcp_manager)
        self.working_dir = working_dir or Path.cwd()
        self.mode_manager = mode_manager
        self.approval_manager = approval_manager
        self.undo_manager = undo_manager
        self.ui_callback = ui_callback

    def parse_args(self, command: str) -> IssueResolverArgs:
        """Parse /resolve-issue command arguments.

        Smart mode detection:
        - If --dataset flag present: SWE-bench mode
        - If GitHub URL present: GitHub mode

        Args:
            command: Full command string

        Returns:
            Parsed arguments

        Raises:
            ValueError: If arguments are missing or invalid
        """
        parts = command.strip().split()

        # SWE-bench mode: --dataset flag present
        if "--dataset" in parts:
            return self._parse_swebench_args(parts)

        # GitHub mode: find full GitHub URL
        for part in parts[1:]:  # Skip command name
            if part.startswith("https://github.com/") and "/issues/" in part:
                return self._parse_github_args(parts, part)

        raise ValueError(
            "Usage:\n"
            "  /resolve-issue https://github.com/owner/repo/issues/123\n"
            "  /resolve-issue --dataset swebench-verified --instance <id>"
        )

    def _parse_swebench_args(self, parts: list[str]) -> IssueResolverArgs:
        """Parse SWE-bench mode arguments."""
        from .swebench_loader import VALID_DATASETS

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
            mode="swebench",
            dataset=dataset,
            instance=instance,
            parallel=parallel,
        )

    def _parse_github_args(self, parts: list[str], url: str) -> IssueResolverArgs:
        """Parse GitHub mode arguments."""
        return IssueResolverArgs(
            mode="github",
            issue_url=url,
        )

    def execute(self, args: IssueResolverArgs) -> ResolveResult:
        """Execute the issue resolution in Docker container.

        Args:
            args: Parsed command arguments

        Returns:
            ResolveResult with success status and details
        """
        if args.mode == "swebench":
            if args.is_batch_mode:
                return self._execute_batch(args)
            return self._execute_swebench_docker(args)
        else:  # github mode
            return self._execute_github_docker(args)

    def _execute_swebench_docker(self, args: IssueResolverArgs) -> ResolveResult:
        """Execute in SWE-bench mode using Docker container.

        Flow:
        1. Load instance from HuggingFace dataset
        2. Start Docker container
        3. Clone repo and checkout base_commit inside container
        4. Execute subagent with Docker runtime
        5. Extract patch from container
        6. Stop container

        Args:
            args: Parsed command arguments with dataset, instance, and docker settings

        Returns:
            ResolveResult with success status and details
        """
        import asyncio

        from swecli.core.docker import DockerConfig, DockerDeployment, DockerToolHandler

        from .swebench_loader import load_swebench_instance

        # Step 1: Load dataset and check instance
        if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
            self.ui_callback.on_progress_start(f"Loading {args.dataset} dataset")

        try:
            instance = load_swebench_instance(args.instance, args.dataset)
        except (ImportError, ValueError) as e:
            if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                self.ui_callback.on_progress_complete(str(e), success=False)
            return ResolveResult(success=False, message=str(e))

        if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
            self.ui_callback.on_progress_complete(
                f"Loaded {instance.instance_id} ({instance.repo} @ {instance.base_commit[:7]})"
            )

        # Step 2: Create Docker deployment config
        # Use SWE-bench pre-built image for this instance
        docker_image = instance.docker_image
        config = DockerConfig(
            image=docker_image,
            memory=args.docker_memory,
            cpus=args.docker_cpus,
        )

        # Use status callback to update Docker progress in-place
        def on_docker_status(msg: str) -> None:
            if self.ui_callback and hasattr(self.ui_callback, "on_progress_update"):
                self.ui_callback.on_progress_update(f"Docker: {msg}")

        deployment = DockerDeployment(config=config, on_status=on_docker_status)

        # Run the async Docker workflow
        async def run_docker_workflow() -> ResolveResult:
            try:
                # Step 3: Start container (single progress line for all Docker setup)
                # Show image name (truncate if too long)
                image_short = docker_image.split("/")[-1][:40]
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
                    self.ui_callback.on_progress_start(f"Docker: Pulling {image_short}...")

                await deployment.start()

                # Get container name for display
                container_name = deployment._container_name

                runtime = deployment.runtime

                # SWE-bench images have repo pre-installed at /testbed
                # with correct commit already checked out - no setup needed!
                repo_path = "/testbed"

                # Create fix branch for our changes
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_update"):
                    self.ui_callback.on_progress_update("Docker: Creating fix branch...")

                branch_name = f"fix/{instance.instance_id}"
                branch_cmd = f"cd {repo_path} && git checkout -b {branch_name}"
                await runtime.run(branch_cmd, timeout=30.0)

                # Complete Docker setup with container name
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                    self.ui_callback.on_progress_complete(f"{container_name} ready")

                # Step 4: Create Docker tool handler
                docker_handler = DockerToolHandler(runtime, workspace_dir=repo_path)

                # Step 5: Build task for subagent
                task = self._build_task(instance, branch_name)

                # Step 6: Execute the Issue-Resolver subagent
                # The subagent will use Docker tools for all operations
                from swecli.core.agents.subagents.manager import SubAgentDeps

                deps = SubAgentDeps(
                    mode_manager=self.mode_manager,
                    approval_manager=self.approval_manager,
                    undo_manager=self.undo_manager,
                )

                # Execute with Docker tool handler - all tool calls route through container
                result = self.subagent_manager.execute_subagent(
                    name="Issue-Resolver",
                    task=task,
                    deps=deps,
                    ui_callback=self.ui_callback,
                    docker_handler=docker_handler,  # Route all tools through Docker
                )

                # Handle string result
                if isinstance(result, str):
                    pass  # Continue to extract patch
                elif not result.get("success"):
                    return ResolveResult(
                        success=False,
                        message=f"Subagent failed: {result.get('error', 'Unknown error')}",
                    )

                # Step 8: Extract patch from container
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
                    self.ui_callback.on_progress_start("Extracting patch from container...")

                patch_cmd = f"cd {repo_path} && git diff {instance.base_commit}"
                obs = await runtime.run(patch_cmd, timeout=60.0)
                patch = obs.output

                # Save patch locally
                repo_name = instance.repo.split("/")[-1]
                patch_dir = self.working_dir / repo_name
                patch_dir.mkdir(parents=True, exist_ok=True)
                patch_path = patch_dir / f"{instance.instance_id}.patch"

                if patch.strip():
                    patch_path.write_text(patch)
                    if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                        self.ui_callback.on_progress_complete(f"Saved to {patch_path}")
                else:
                    patch_path = None
                    if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                        self.ui_callback.on_progress_complete("No changes detected", success=False)

                return ResolveResult(
                    success=True,
                    message=f"SWE-bench instance {instance.instance_id} resolved in Docker",
                    patch=patch,
                    prediction_path=patch_path,
                )

            finally:
                # Step 9: Stop container
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
                    self.ui_callback.on_progress_start("Stopping container...")
                await deployment.stop()
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                    self.ui_callback.on_progress_complete("Container stopped")

        # Run the async workflow
        return asyncio.run(run_docker_workflow())

    def _build_task(self, instance: Any, branch_name: str) -> str:
        """Build task description for Docker-based execution.

        SWE-bench images have the repo pre-installed at /testbed.
        """
        return f"""Fix issue {instance.instance_id}

REPO: /testbed
BRANCH: {branch_name}
COMMIT: {instance.base_commit}

## Problem

{instance.problem_statement}

## Instructions

Follow the MANDATORY WORKFLOW in your system prompt. Start with Step 1 (VERIFY SETUP).

IMPORTANT: The repository is at /testbed (SWE-bench convention).
Use absolute paths like: /testbed/path/to/file.py
"""

    def _execute_batch(self, args: IssueResolverArgs) -> ResolveResult:
        """Execute in batch mode (whole dataset).

        Runs all instances in the dataset using Docker containers,
        with auto-skip for completed ones and optional parallel execution.

        Args:
            args: Parsed command arguments with dataset and parallel

        Returns:
            ResolveResult with batch completion status
        """
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
            if not (predictions_dir / f"{inst}.patch").exists()
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

        # Execute instances sequentially (each gets its own Docker container)
        succeeded = 0
        failed = 0

        for i, instance_id in enumerate(pending, 1):
            if self.ui_callback and hasattr(self.ui_callback, "on_message"):
                self.ui_callback.on_message(f"[{i}/{len(pending)}] Resolving {instance_id}...")

            # Create args for single instance
            single_args = IssueResolverArgs(
                mode="swebench",
                dataset=args.dataset,
                instance=instance_id,
            )

            result = self._execute_swebench_docker(single_args)
            if result.success:
                succeeded += 1
            else:
                failed += 1

        return ResolveResult(
            success=True,
            message=f"Batch complete: {succeeded} resolved, {failed} failed out of {total} total",
        )

    def _execute_github_docker(self, args: IssueResolverArgs) -> ResolveResult:
        """Execute GitHub issue resolution in Docker container.

        Flow:
        1. Parse URL and fetch issue via GitHub MCP
        2. Start generic Docker container
        3. Clone repo inside container
        4. Execute GitHub-Resolver subagent
        5. Extract patch from container
        6. Stop container

        Args:
            args: Parsed command arguments with issue_url

        Returns:
            ResolveResult with success status and details
        """
        import asyncio

        from swecli.core.docker import DockerConfig, DockerDeployment, DockerToolHandler

        from .url_parser import parse_github_issue_url

        # Step 1: Parse URL
        issue_info = parse_github_issue_url(args.issue_url)
        if not issue_info:
            return ResolveResult(
                success=False,
                message=f"Invalid GitHub issue URL: {args.issue_url}",
            )

        # Step 2: Ensure GitHub MCP is connected
        if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
            self.ui_callback.on_progress_start("Connecting to GitHub...")

        connected, msg = self.mcp_github.ensure_connected()
        if not connected:
            if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                self.ui_callback.on_progress_complete(msg, success=False)
            return ResolveResult(
                success=False,
                message=f"GitHub connection failed: {msg}",
            )

        # Step 3: Fetch issue details
        issue = self.mcp_github.get_issue(
            issue_info.owner, issue_info.repo, issue_info.issue_number
        )
        if not issue:
            if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                self.ui_callback.on_progress_complete("Failed to fetch issue", success=False)
            return ResolveResult(
                success=False,
                message="Failed to fetch issue details from GitHub",
            )

        if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
            self.ui_callback.on_progress_complete(
                f"Fetched #{issue.number}: {issue.title[:50]}..."
            )

        # Step 4: Create Docker deployment config (generic Python image)
        config = DockerConfig(
            image="python:3.11-slim",
            memory=args.docker_memory,
            cpus=args.docker_cpus,
        )

        def on_docker_status(msg: str) -> None:
            if self.ui_callback and hasattr(self.ui_callback, "on_progress_update"):
                self.ui_callback.on_progress_update(f"Docker: {msg}")

        deployment = DockerDeployment(config=config, on_status=on_docker_status)

        # Run the async Docker workflow
        async def run_docker_workflow() -> ResolveResult:
            try:
                # Step 5: Start container
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
                    self.ui_callback.on_progress_start("Docker: Starting container...")

                await deployment.start()
                container_name = deployment._container_name
                runtime = deployment.runtime

                # Step 6: Install git in container (python:3.11-slim doesn't have it)
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_update"):
                    self.ui_callback.on_progress_update("Docker: Installing git...")

                await runtime.run("apt-get update && apt-get install -y git", timeout=120.0)

                # Step 7: Clone repo inside container
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_update"):
                    self.ui_callback.on_progress_update("Docker: Cloning repository...")

                repo_url = f"https://github.com/{issue_info.owner}/{issue_info.repo}.git"
                clone_cmd = f"git clone --depth 1 {repo_url} /workspace"
                await runtime.run(clone_cmd, timeout=120.0)

                # Step 8: Create fix branch
                branch_name = f"fix/issue-{issue_info.issue_number}"
                branch_cmd = f"cd /workspace && git checkout -b {branch_name}"
                await runtime.run(branch_cmd, timeout=30.0)

                if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                    self.ui_callback.on_progress_complete(f"{container_name} ready")

                # Step 9: Create Docker tool handler
                docker_handler = DockerToolHandler(runtime, workspace_dir="/workspace")

                # Step 10: Build task for subagent
                task = self._build_github_task(issue, issue_info, branch_name)

                # Step 11: Execute the GitHub-Resolver subagent
                from swecli.core.agents.subagents.manager import SubAgentDeps

                deps = SubAgentDeps(
                    mode_manager=self.mode_manager,
                    approval_manager=self.approval_manager,
                    undo_manager=self.undo_manager,
                )

                result = self.subagent_manager.execute_subagent(
                    name="GitHub-Resolver",
                    task=task,
                    deps=deps,
                    ui_callback=self.ui_callback,
                    docker_handler=docker_handler,
                )

                # Handle string result
                if isinstance(result, str):
                    pass  # Continue to extract patch
                elif not result.get("success"):
                    return ResolveResult(
                        success=False,
                        message=f"Subagent failed: {result.get('error', 'Unknown error')}",
                    )

                # Step 12: Extract patch from container
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
                    self.ui_callback.on_progress_start("Extracting patch...")

                # Get diff of all changes (committed or not)
                patch_cmd = "cd /workspace && git diff HEAD"
                obs = await runtime.run(patch_cmd, timeout=60.0)
                patch = obs.output

                # If no uncommitted changes, get diff from initial commit
                if not patch.strip():
                    patch_cmd = "cd /workspace && git diff HEAD~1 HEAD 2>/dev/null || git diff --cached"
                    obs = await runtime.run(patch_cmd, timeout=60.0)
                    patch = obs.output

                # Save patch locally
                patch_dir = self.working_dir / "github-issues" / issue_info.owner / issue_info.repo
                patch_dir.mkdir(parents=True, exist_ok=True)
                patch_path = patch_dir / f"issue-{issue_info.issue_number}.patch"

                if patch.strip():
                    patch_path.write_text(patch)
                    if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                        self.ui_callback.on_progress_complete(f"Saved to {patch_path}")
                else:
                    patch_path = None
                    if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                        self.ui_callback.on_progress_complete("No changes detected", success=False)

                return ResolveResult(
                    success=True,
                    message=f"GitHub issue #{issue_info.issue_number} resolved",
                    patch=patch,
                    prediction_path=patch_path,
                )

            finally:
                # Step 13: Stop container
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_start"):
                    self.ui_callback.on_progress_start("Stopping container...")
                await deployment.stop()
                if self.ui_callback and hasattr(self.ui_callback, "on_progress_complete"):
                    self.ui_callback.on_progress_complete("Container stopped")

        # Run the async workflow
        return asyncio.run(run_docker_workflow())

    def _build_github_task(self, issue: Any, issue_info: Any, branch_name: str) -> str:
        """Build task description for GitHub issue resolution."""
        return f"""Fix GitHub issue #{issue_info.issue_number}

REPO: /workspace
BRANCH: {branch_name}
OWNER: {issue_info.owner}
REPO_NAME: {issue_info.repo}

## Issue: {issue.title}

{issue.body}

## Instructions

Follow the MANDATORY WORKFLOW in your system prompt. Start with Step 1 (VERIFY SETUP).

IMPORTANT: The repository is cloned at /workspace.
Use absolute paths like: /workspace/path/to/file.py
"""
