"""Command handler for /paper2code command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from swecli.core.agents.subagents.manager import SubAgentManager


@dataclass
class Paper2CodeArgs:
    """Arguments for /paper2code command."""

    pdf_path: str


@dataclass
class Paper2CodeResult:
    """Result of paper2code execution."""

    success: bool
    message: str
    output_path: Optional[Path] = None


class Paper2CodeCommand:
    """Handler for Paper2Code subagent execution."""

    def __init__(
        self,
        subagent_manager: "SubAgentManager",
        working_dir: Optional[Path] = None,
        mode_manager: Optional[Any] = None,
        approval_manager: Optional[Any] = None,
        undo_manager: Optional[Any] = None,
        ui_callback: Optional[Any] = None,
    ):
        """Initialize paper2code command.

        Args:
            subagent_manager: SubAgentManager for spawning subagents
            working_dir: Working directory for file operations
            mode_manager: Mode manager for subagent deps
            approval_manager: Approval manager for subagent deps
            undo_manager: Undo manager for subagent deps
            ui_callback: UI callback for displaying progress
        """
        self.subagent_manager = subagent_manager
        self.working_dir = working_dir or Path.cwd()
        self.mode_manager = mode_manager
        self.approval_manager = approval_manager
        self.undo_manager = undo_manager
        self.ui_callback = ui_callback

    def parse_args(self, command: str) -> Paper2CodeArgs:
        """Parse /paper2code command arguments.

        Format: /paper2code <path_to_pdf>

        Args:
            command: Full command string

        Returns:
            Parsed arguments

        Raises:
            ValueError: If arguments are missing or invalid
        """
        parts = command.strip().split()
        if len(parts) != 2:
            raise ValueError("Usage: /paper2code <path_to_pdf>")

        pdf_path = parts[1]
        
        # Handle @ mention syntax from autocomplete
        if pdf_path.startswith("@"):
            pdf_path = pdf_path[1:]

        return Paper2CodeArgs(
            pdf_path=pdf_path,
        )

    def execute(self, args: Paper2CodeArgs) -> Paper2CodeResult:
        """Execute the paper2code subagent.

        Args:
            args: Parsed command arguments

        Returns:
            Paper2CodeResult with success status and details
        """
        # Resolve paths
        pdf_path = Path(args.pdf_path).expanduser().resolve()
        if not pdf_path.exists():
            return Paper2CodeResult(
                success=False,
                message=f"PDF file not found: {pdf_path}",
            )

        # Always create a new directory named after the PDF in the current working directory
        target_dir = self.working_dir / pdf_path.stem

        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)

        # Build task
        task = self._build_task(str(pdf_path), str(target_dir))

        # Prepare dependencies
        from swecli.core.agents.subagents.manager import SubAgentDeps

        deps = SubAgentDeps(
            mode_manager=self.mode_manager,
            approval_manager=self.approval_manager,
            undo_manager=self.undo_manager,
        )

        # Execute subagent
        result = self.subagent_manager.execute_subagent(
            name="Paper2Code",
            task=task,
            deps=deps,
            ui_callback=self.ui_callback,
            working_dir=target_dir,  # Agent works in the target directory
        )

        if isinstance(result, dict) and not result.get("success"):
            return Paper2CodeResult(
                success=False,
                message=f"Subagent failed: {result.get('error', 'Unknown error')}",
            )

        return Paper2CodeResult(
            success=True,
            message=f"Paper implemented in {target_dir}",
            output_path=target_dir,
        )

    def _build_task(self, pdf_path: str, output_dir: str) -> str:
        """Build the task description for the subagent."""
        return f"""Implement the research paper found at: {pdf_path}

The goal is to create a complete, runnable codebase implementation of this paper.
You are working in: {output_dir}

Follow the defined 4-stage pipeline:
1. Planning (Analysis & Design)
2. Analysis (Detailed Logic)
3. Coding (Implementation)
4. Debugging (Verification)

Read the PDF first using `read_pdf`.
"""
