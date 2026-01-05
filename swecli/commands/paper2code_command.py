"""Command handler for /paper2code command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from swecli.commands.subagent_mixin import CommandPhase, SubagentProgressMixin
from swecli.commands.subagent_types import OutputMetadata, SubagentCommandResult

if TYPE_CHECKING:
    from swecli.core.agents.subagents.manager import SubAgentManager


@dataclass
class Paper2CodeArgs:
    """Arguments for /paper2code command."""

    pdf_path: str


# Backwards compatibility alias
Paper2CodeResult = SubagentCommandResult


class Paper2CodeCommand(SubagentProgressMixin):
    """Handler for Paper2Code subagent execution."""

    def _verify_output(self, target_dir: Path) -> SubagentCommandResult:
        """Verify the generated project is at least minimally runnable.

        Checks:
        - main.py exists
        - dependency installation succeeds (best-effort)
        - running main.py succeeds (best-effort)

        Notes:
            This runs on the host (not in the subagent Docker). It is meant as a
            safety net to catch obvious cases where the agent skipped Stage 4.
        """
        self.show_progress("Verifying output...", CommandPhase.VERIFYING)

        main_py = target_dir / "main.py"
        if not main_py.exists():
            return SubagentCommandResult(
                success=False,
                message=f"Verification failed: missing entrypoint {main_py.name}",
                metadata=OutputMetadata(output_path=target_dir),
            )

        # Prefer uv if available; fall back to python -m pip.
        install_cmds = [
            "uv pip install -e .",
            "python -m pip install -e .",
        ]

        install_ok = False
        last_install_output = ""
        for cmd in install_cmds:
            try:
                import subprocess

                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=str(target_dir),
                    capture_output=True,
                    text=True,
                )
                last_install_output = (proc.stdout or "") + (proc.stderr or "")
                if proc.returncode == 0:
                    install_ok = True
                    break
            except Exception as e:  # noqa: BLE001
                last_install_output = str(e)

        if not install_ok:
            # Don't dump huge logs; include a small tail.
            tail = "\n".join(last_install_output.splitlines()[-20:])
            return SubagentCommandResult(
                success=False,
                message=(
                    "Verification failed: could not install generated project dependencies.\n"
                    "Tried: uv pip install -e . and python -m pip install -e .\n"
                    f"Output (tail):\n{tail}"
                ),
                metadata=OutputMetadata(output_path=target_dir),
            )

        # Run entrypoint.
        try:
            import subprocess

            proc = subprocess.run(
                "python main.py",
                shell=True,
                cwd=str(target_dir),
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                out = (proc.stdout or "") + (proc.stderr or "")
                tail = "\n".join(out.splitlines()[-40:])
                return SubagentCommandResult(
                    success=False,
                    message=f"Verification failed: running main.py exited with {proc.returncode}.\nOutput (tail):\n{tail}",
                    metadata=OutputMetadata(output_path=target_dir),
                )
        except Exception as e:  # noqa: BLE001
            return SubagentCommandResult(
                success=False,
                message=f"Verification failed: could not run main.py ({e})",
                metadata=OutputMetadata(output_path=target_dir),
            )

        self.complete_progress("Verification passed")
        return SubagentCommandResult(
            success=True,
            message="Verification succeeded",
            metadata=OutputMetadata(output_path=target_dir),
        )

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

    def execute(self, args: Paper2CodeArgs) -> SubagentCommandResult:
        """Execute the paper2code subagent.

        Args:
            args: Parsed command arguments

        Returns:
            SubagentCommandResult with success status and details
        """
        # Resolve paths
        self.show_progress("Resolving paths...", CommandPhase.LOADING)
        pdf_path = Path(args.pdf_path).expanduser().resolve()
        if not pdf_path.exists():
            return SubagentCommandResult(
                success=False,
                message=f"PDF file not found: {pdf_path}",
            )

        # Always create a new directory named after the PDF in the current working directory
        target_dir = self.working_dir / pdf_path.stem

        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
        self.complete_progress(f"Output directory: {target_dir}")

        # Build task
        task = self._build_task(str(pdf_path), str(target_dir))

        # Prepare dependencies
        from swecli.core.agents.subagents.manager import SubAgentDeps

        deps = SubAgentDeps(
            mode_manager=self.mode_manager,
            approval_manager=self.approval_manager,
            undo_manager=self.undo_manager,
        )

        # Show spawn header and execute subagent
        self.show_spawn_header("Paper2Code", f"Implement {pdf_path.name}")
        result = self.subagent_manager.execute_subagent(
            name="Paper2Code",
            task=task,
            deps=deps,
            ui_callback=self.ui_callback,
            working_dir=target_dir,  # Agent works in the target directory
            show_spawn_header=False,  # We already showed it via mixin
        )

        if isinstance(result, dict) and not result.get("success"):
            error_msg = result.get("error") or result.get("content") or "Unknown error"
            return SubagentCommandResult(
                success=False,
                message=f"Subagent failed: {error_msg}",
                metadata=OutputMetadata(output_path=target_dir),
            )

        # Post-run verification: ensure the agent produced a runnable project.
        # This is a lightweight guardrail in case the agent skipped Stage 4.
        verification = self._verify_output(target_dir)
        if not verification.success:
            return SubagentCommandResult(
                success=False,
                message=verification.message,
                metadata=OutputMetadata(output_path=target_dir),
            )

        return SubagentCommandResult(
            success=True,
            message=f"Paper implemented in {target_dir}",
            metadata=OutputMetadata(output_path=target_dir),
        )

    def _build_task(self, pdf_path: str, output_dir: str) -> str:
        """Build the task description for the subagent."""
        pdf_name = Path(pdf_path).name

        return f"""Implement the research paper: {pdf_name}

Create a minimal, runnable Python implementation with:
- pyproject.toml with dependencies
- config.yaml with paper's hyperparameters
- main.py CLI entrypoint that runs a demo
- Core implementation modules
- README.md with usage

IMPORTANT: Do NOT stop until main.py exists and runs successfully.
Test with: uv pip install -e . --system && python main.py
"""
