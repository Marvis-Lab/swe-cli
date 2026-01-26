"""RalphOrchestrator - Main loop controller for Ralph autonomous agent."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from rich.console import Console

from swecli.ralph.models.prd import RalphPRD
from swecli.ralph.models.progress import ProgressEntry, RalphProgressLog
from swecli.ralph.quality.gates import QualityGateRunner, QualityGateResult
from swecli.ralph.agents.ralph_agent import RalphAgent, RalphAgentResult


logger = logging.getLogger(__name__)


class ApprovalMode(Enum):
    """How approval is handled during Ralph runs."""

    AUTO = "auto"  # No approval required
    PER_STORY = "per_story"  # Approve after each story
    PER_ITERATION = "per_iteration"  # Approve after each iteration


@dataclass
class RalphConfig:
    """Configuration for Ralph runs."""

    max_iterations: int = 10
    approval_mode: ApprovalMode = ApprovalMode.AUTO
    skip_tests: bool = False
    auto_commit: bool = True
    prd_path: Path = Path("prd.json")
    progress_path: Path = Path("progress.txt")


@dataclass
class IterationResult:
    """Result from a single Ralph iteration."""

    iteration: int
    story_id: str
    success: bool
    agent_result: Optional[RalphAgentResult] = None
    quality_result: Optional[QualityGateResult] = None
    committed: bool = False
    error: Optional[str] = None


class RalphOrchestrator:
    """Main orchestrator for Ralph autonomous agent loop.

    Manages the iteration cycle:
    1. Load PRD and pick next story
    2. Ensure correct git branch
    3. Spawn fresh agent for story
    4. Run quality gates
    5. Commit if passing
    6. Update PRD and progress log
    7. Repeat until complete or max iterations
    """

    COMPLETE_SIGNAL = "<promise>COMPLETE</promise>"

    def __init__(
        self,
        working_dir: Path,
        config: RalphConfig,
        console: Optional[Console] = None,
        on_iteration_complete: Optional[Callable[[IterationResult], None]] = None,
    ):
        """Initialize the orchestrator.

        Args:
            working_dir: Project working directory
            config: Ralph configuration
            console: Rich console for output
            on_iteration_complete: Callback after each iteration
        """
        self.working_dir = working_dir
        self.config = config
        self.console = console or Console()
        self.on_iteration_complete = on_iteration_complete

        self.prd_path = working_dir / config.prd_path
        self.progress_path = working_dir / config.progress_path

        self._prd: Optional[RalphPRD] = None
        self._progress: Optional[RalphProgressLog] = None
        self._quality_runner: Optional[QualityGateRunner] = None

    def _load_prd(self) -> RalphPRD:
        """Load PRD from file."""
        if not self.prd_path.exists():
            raise FileNotFoundError(f"PRD not found: {self.prd_path}")
        return RalphPRD.load(self.prd_path)

    def _init_progress(self) -> RalphProgressLog:
        """Initialize or load progress log."""
        progress = RalphProgressLog(self.progress_path)
        if not self.progress_path.exists():
            progress.initialize()
        return progress

    def _ensure_branch(self, branch_name: str) -> bool:
        """Ensure we're on the correct git branch.

        Args:
            branch_name: Expected branch name

        Returns:
            True if on correct branch or successfully switched
        """
        try:
            # Check current branch
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            current_branch = result.stdout.strip()

            if current_branch == branch_name:
                return True

            # Try to checkout or create branch
            self.console.print(f"[yellow]Switching to branch: {branch_name}[/yellow]")

            # First try checkout (in case branch exists)
            result = subprocess.run(
                ["git", "checkout", branch_name],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                # Create new branch from main
                subprocess.run(
                    ["git", "checkout", "-b", branch_name, "main"],
                    cwd=self.working_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )

            return True

        except subprocess.CalledProcessError as e:
            self.console.print(f"[red]Git error: {e.stderr}[/red]")
            return False

    def _commit_changes(self, story_id: str, story_title: str) -> bool:
        """Commit all changes with a standard message.

        Args:
            story_id: Story ID for commit message
            story_title: Story title for commit message

        Returns:
            True if commit succeeded
        """
        try:
            # Stage all changes
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self.working_dir,
                capture_output=True,
                check=True,
            )

            # Check if there are changes to commit
            result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=self.working_dir,
                capture_output=True,
            )

            if result.returncode == 0:
                # No changes to commit
                return True

            # Commit with standard message
            commit_msg = f"feat: {story_id} - {story_title}"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                check=True,
            )

            return True

        except subprocess.CalledProcessError as e:
            self.console.print(f"[red]Commit failed: {e.stderr}[/red]")
            return False

    def _create_agent(
        self,
        swecli_agent: Any,
        prd: RalphPRD,
        progress: RalphProgressLog,
    ) -> RalphAgent:
        """Create a fresh Ralph agent.

        Args:
            swecli_agent: Base SwecliAgent instance
            prd: Current PRD
            progress: Progress log

        Returns:
            New RalphAgent instance
        """
        return RalphAgent(
            swecli_agent=swecli_agent,
            prd=prd,
            progress_log=progress,
            working_dir=self.working_dir,
        )

    def run(
        self,
        swecli_agent: Any,
        deps: Any,
        task_monitor: Optional[Any] = None,
        ui_callback: Optional[Any] = None,
    ) -> bool:
        """Run the Ralph iteration loop.

        Args:
            swecli_agent: SwecliAgent to use for iterations
            deps: Agent dependencies
            task_monitor: Optional task monitor for interrupts
            ui_callback: Optional UI callback

        Returns:
            True if all stories completed successfully
        """
        # Load PRD and progress
        self._prd = self._load_prd()
        self._progress = self._init_progress()
        self._quality_runner = QualityGateRunner(self.working_dir)

        self.console.print("\n[bold cyan]Starting Ralph[/bold cyan]")
        self.console.print(f"Project: {self._prd.project}")
        self.console.print(f"Branch: {self._prd.branch_name}")
        self.console.print(f"Stories: {len(self._prd.user_stories)}")
        self.console.print(f"Max iterations: {self.config.max_iterations}\n")

        # Ensure correct branch
        if not self._ensure_branch(self._prd.branch_name):
            self.console.print("[red]Failed to switch to correct branch[/red]")
            return False

        iteration = 0
        while iteration < self.config.max_iterations:
            iteration += 1

            # Check for completion
            if self._prd.is_complete():
                self.console.print(f"\n[bold green]{self.COMPLETE_SIGNAL}[/bold green]")
                self.console.print(f"All stories complete after {iteration - 1} iterations!")
                return True

            # Get next story
            story = self._prd.get_next_story()
            if not story:
                self.console.print("[yellow]No more stories to process[/yellow]")
                return True

            self.console.print(f"\n{'='*60}")
            self.console.print(
                f"[bold]Iteration {iteration}/{self.config.max_iterations}[/bold]"
            )
            self.console.print(f"Story: [{story.id}] {story.title}")
            self.console.print(f"{'='*60}\n")

            # Create fresh agent for this iteration
            ralph_agent = self._create_agent(swecli_agent, self._prd, self._progress)

            # Execute story
            agent_result = ralph_agent.execute_story(
                story=story,
                deps=deps,
                task_monitor=task_monitor,
                ui_callback=ui_callback,
            )

            iteration_result = IterationResult(
                iteration=iteration,
                story_id=story.id,
                success=False,
                agent_result=agent_result,
            )

            if not agent_result.success:
                self.console.print(f"[red]Story failed: {agent_result.error}[/red]")
                self._record_progress(story, agent_result, False)
                iteration_result.error = agent_result.error

                if self.on_iteration_complete:
                    self.on_iteration_complete(iteration_result)
                continue

            # Run quality gates
            self.console.print("\n[cyan]Running quality gates...[/cyan]")
            quality_result = self._quality_runner.run_all(skip_tests=self.config.skip_tests)
            iteration_result.quality_result = quality_result

            if not quality_result.success:
                self.console.print("[red]Quality gates failed:[/red]")
                self.console.print(quality_result.get_summary())
                self._record_progress(story, agent_result, False, quality_result)

                if self.on_iteration_complete:
                    self.on_iteration_complete(iteration_result)
                continue

            self.console.print("[green]Quality gates passed![/green]")

            # Commit changes
            if self.config.auto_commit:
                if self._commit_changes(story.id, story.title):
                    self.console.print(f"[green]Committed: feat: {story.id} - {story.title}[/green]")
                    iteration_result.committed = True
                else:
                    self.console.print("[yellow]No changes to commit[/yellow]")

            # Mark story complete and save
            self._prd.mark_story_complete(story.id)
            self._prd.save(self.prd_path)

            # Record progress
            self._record_progress(story, agent_result, True, quality_result)

            # Add learnings to patterns
            for learning in agent_result.learnings:
                self._progress.add_pattern(learning)

            iteration_result.success = True

            if self.on_iteration_complete:
                self.on_iteration_complete(iteration_result)

            # Check approval mode
            if self.config.approval_mode == ApprovalMode.PER_STORY:
                if not self._prompt_continue():
                    self.console.print("[yellow]Stopped by user[/yellow]")
                    return False

        # Max iterations reached
        self.console.print(
            f"\n[yellow]Max iterations ({self.config.max_iterations}) reached[/yellow]"
        )
        self.console.print(self._prd.get_progress_summary())
        return False

    def _record_progress(
        self,
        story: Any,
        agent_result: RalphAgentResult,
        success: bool,
        quality_result: Optional[QualityGateResult] = None,
    ) -> None:
        """Record progress entry.

        Args:
            story: The story worked on
            agent_result: Agent execution result
            success: Whether the iteration succeeded
            quality_result: Optional quality gate result
        """
        if not self._progress:
            return

        error = None
        if not success:
            if quality_result and quality_result.errors:
                error = "; ".join(quality_result.errors)
            elif agent_result.error:
                error = agent_result.error

        entry = ProgressEntry(
            timestamp=datetime.now(),
            story_id=story.id,
            summary=agent_result.summary,
            files_changed=agent_result.files_changed,
            learnings=agent_result.learnings,
            success=success,
            error=error,
        )

        self._progress.append_entry(entry)

    def _prompt_continue(self) -> bool:
        """Prompt user to continue.

        Returns:
            True to continue, False to stop
        """
        try:
            response = input("\nContinue to next story? [Y/n]: ").strip().lower()
            return response != "n"
        except (EOFError, KeyboardInterrupt):
            return False

    def get_status(self) -> str:
        """Get current PRD status.

        Returns:
            Status summary string
        """
        if not self.prd_path.exists():
            return "No PRD found. Run 'swecli ralph create' first."

        prd = self._load_prd()
        return prd.get_progress_summary()
