"""Init command for codebase analysis and memory creation."""

from pathlib import Path
from typing import Any
from pydantic import BaseModel

from rich.console import Console

from swecli.models.agent_deps import AgentDependencies
from swecli.core.agents.prompts import load_prompt


class InitCommandArgs(BaseModel):
    """Arguments for /init command."""

    path: Path = Path.cwd()
    skip_patterns: list[str] = [".git", "node_modules", "__pycache__", "venv", ".venv", "build", "dist"]


class InitCommandHandler:
    """Handles /init command execution.

    The handler orchestrates the codebase analysis by delegating to
    the Pydantic AI agent with a specialized system prompt.
    """

    def __init__(self, agent: Any, console: Console):
        """Initialize init command handler.

        Args:
            agent: OpenDev Pydantic AI Agent
            console: Rich console for output
        """
        self.agent = agent
        self.console = console

    def parse_args(self, command: str) -> InitCommandArgs:
        """Parse /init command arguments.

        Args:
            command: The full command string (e.g., "/init" or "/init /path/to/project")

        Returns:
            Parsed arguments

        Examples:
            >>> parse_args("/init")
            InitCommandArgs(path=Path.cwd())

            >>> parse_args("/init ~/projects/myapp")
            InitCommandArgs(path=Path("~/projects/myapp").expanduser())
        """
        parts = command.strip().split()

        # Default: current directory
        if len(parts) == 1:
            return InitCommandArgs()

        # Custom path provided
        path_str = parts[1]
        path = Path(path_str).expanduser().absolute()

        return InitCommandArgs(path=path)

    def execute(self, args: InitCommandArgs, deps: AgentDependencies) -> dict[str, Any]:
        """Execute init command.

        This method creates a specialized task for the AI agent to analyze
        the codebase and generate AGENTS.md. The agent performs a comprehensive
        analysis of the project structure, dependencies, and architecture.

        Args:
            args: Parsed command arguments
            deps: Agent dependencies

        Returns:
            Result dictionary with success status and message
        """
        # Validate path
        if not args.path.exists():
            return {
                "success": False,
                "message": f"Path does not exist: {args.path}"
            }

        if not args.path.is_dir():
            return {
                "success": False,
                "message": f"Path is not a directory: {args.path}"
            }

        # Change working directory context
        original_cwd = Path.cwd()
        deps.working_dir = args.path

        try:
            # Create specialized prompt for codebase analysis
            task_prompt = self._create_analysis_prompt(args.path)

            # Show progress
            self.console.print(f"[cyan]Analyzing codebase at {args.path}...[/cyan]")

            # Run agent with analysis task
            result = self.agent.run_sync(
                message=task_prompt,
                deps=deps,
            )

            if result["success"]:
                agents_path = args.path / "AGENTS.md"

                # Check if agent wrote the file
                if not agents_path.exists():
                    # Agent didn't write file - extract content and write it
                    content = result.get("content", "")
                    if content:
                        agents_path.write_text(content)
                        self.console.print("[yellow]Note: Agent didn't write file, wrote manually[/yellow]")

                return {
                    "success": True,
                    "message": f"✓ Generated AGENTS.md at {agents_path}",
                    "content": result["content"]
                }
            else:
                return {
                    "success": False,
                    "message": f"✗ Failed to generate AGENTS.md: {result.get('content', 'Unknown error')}"
                }

        finally:
            # Restore working directory
            deps.working_dir = original_cwd

    def _create_analysis_prompt(self, path: Path) -> str:
        """Create specialized prompt for codebase analysis.

        Args:
            path: Path to analyze

        Returns:
            Prompt string for the agent
        """
        # Load prompt template from file
        template = load_prompt("init_analysis")

        # Replace path placeholder
        return template.replace("{path}", str(path))

