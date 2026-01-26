"""CLI handlers for Ralph commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from swecli.ui_textual.style_tokens import CYAN, ERROR, SUCCESS, WARNING


def create_ralph_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Create the ralph subparser.

    Args:
        subparsers: Parent subparsers to add to

    Returns:
        The ralph subparser
    """
    ralph_parser = subparsers.add_parser(
        "ralph",
        help="Run Ralph autonomous agent loop",
        description="Ralph spawns fresh AI instances per iteration to implement user stories from a PRD",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  swecli ralph create "Add user authentication"    # Generate PRD from description
  swecli ralph run                                 # Run autonomous loop
  swecli ralph run --max-iterations 5              # Limit iterations
  swecli ralph status                              # Show PRD progress
        """,
    )

    ralph_subparsers = ralph_parser.add_subparsers(dest="ralph_command", help="Ralph operations")

    # ralph create
    create_parser = ralph_subparsers.add_parser(
        "create",
        help="Generate a PRD from a feature description",
        description="Uses AI to create a structured PRD with user stories",
    )
    create_parser.add_argument(
        "description",
        help="Feature description (e.g., 'Add user authentication with OAuth')",
    )
    create_parser.add_argument(
        "--output",
        "-o",
        default="prd.json",
        help="Output path for PRD file (default: prd.json)",
    )
    create_parser.add_argument(
        "--branch",
        "-b",
        help="Git branch name (default: ralph/<feature-slug>)",
    )

    # ralph run
    run_parser = ralph_subparsers.add_parser(
        "run",
        help="Run the autonomous agent loop",
        description="Iteratively implement user stories from the PRD",
    )
    run_parser.add_argument(
        "--max-iterations",
        "-m",
        type=int,
        default=10,
        help="Maximum iterations before stopping (default: 10)",
    )
    run_parser.add_argument(
        "--prd",
        default="prd.json",
        help="Path to PRD file (default: prd.json)",
    )
    run_parser.add_argument(
        "--approval",
        choices=["auto", "per-story", "per-iteration"],
        default="auto",
        help="Approval mode: auto (no approval), per-story, or per-iteration",
    )
    run_parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running tests in quality gates (faster but less safe)",
    )
    run_parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Don't auto-commit after successful stories",
    )

    # ralph status
    status_parser = ralph_subparsers.add_parser(
        "status",
        help="Show PRD progress",
        description="Display current status of all user stories",
    )
    status_parser.add_argument(
        "--prd",
        default="prd.json",
        help="Path to PRD file (default: prd.json)",
    )

    return ralph_parser


def handle_ralph_command(args: argparse.Namespace) -> None:
    """Handle ralph subcommands.

    Args:
        args: Parsed command-line arguments
    """
    console = Console()

    if not args.ralph_command:
        console.print(
            f"[{WARNING}]No ralph subcommand specified. Use --help for available commands.[/{WARNING}]"
        )
        sys.exit(1)

    if args.ralph_command == "create":
        _handle_create(args, console)
    elif args.ralph_command == "run":
        _handle_run(args, console)
    elif args.ralph_command == "status":
        _handle_status(args, console)


def _handle_create(args: argparse.Namespace, console: Console) -> None:
    """Handle 'ralph create' command.

    Args:
        args: Parsed arguments
        console: Rich console
    """
    from swecli.core.runtime import ConfigManager
    from swecli.ralph.agents.prd_agent import PRDAgent

    working_dir = Path.cwd()
    output_path = working_dir / args.output

    if output_path.exists():
        console.print(f"[{WARNING}]PRD already exists: {output_path}[/{WARNING}]")
        response = input("Overwrite? [y/N]: ").strip().lower()
        if response != "y":
            console.print("Cancelled.")
            return

    console.print(f"[{CYAN}]Generating PRD from description...[/{CYAN}]")
    console.print(f"Description: {args.description}\n")

    try:
        # Initialize config
        config_manager = ConfigManager(working_dir)
        config = config_manager.load_config()

        # Generate PRD
        prd_agent = PRDAgent(config, working_dir)
        prd = prd_agent.generate_prd(
            description=args.description,
            branch_name=args.branch,
        )

        # Save PRD
        prd.save(output_path)

        console.print(f"[{SUCCESS}]PRD created: {output_path}[/{SUCCESS}]\n")

        # Display summary
        table = Table(title="User Stories", show_header=True, header_style="bold cyan")
        table.add_column("ID", style="cyan")
        table.add_column("Title")
        table.add_column("Priority", justify="center")

        for story in prd.user_stories:
            table.add_row(story.id, story.title, str(story.priority))

        console.print(table)
        console.print(f"\nBranch: {prd.branch_name}")
        console.print("\nRun 'swecli ralph run' to start implementation.")

    except Exception as e:
        console.print(f"[{ERROR}]Error generating PRD: {e}[/{ERROR}]")
        sys.exit(1)


def _handle_run(args: argparse.Namespace, console: Console) -> None:
    """Handle 'ralph run' command.

    Args:
        args: Parsed arguments
        console: Rich console
    """
    from swecli.core.runtime import ConfigManager, ModeManager
    from swecli.core.runtime.approval import ApprovalManager
    from swecli.core.context_engineering.history import SessionManager, UndoManager
    from swecli.core.runtime.services import RuntimeService
    from swecli.models.agent_deps import AgentDependencies
    from swecli.ralph.orchestrator import RalphOrchestrator, RalphConfig, ApprovalMode
    from swecli.core.context_engineering.tools.implementations import (
        BashTool,
        EditTool,
        FileOperations,
        VLMTool,
        WebFetchTool,
        WriteTool,
    )
    from swecli.core.context_engineering.tools.implementations.web_search_tool import WebSearchTool
    from swecli.core.context_engineering.tools.implementations.notebook_edit_tool import (
        NotebookEditTool,
    )
    from swecli.core.context_engineering.tools.implementations.ask_user_tool import AskUserTool

    working_dir = Path.cwd()
    prd_path = working_dir / args.prd

    if not prd_path.exists():
        console.print(f"[{ERROR}]PRD not found: {prd_path}[/{ERROR}]")
        console.print("Run 'swecli ralph create \"description\"' first.")
        sys.exit(1)

    # Parse approval mode
    approval_map = {
        "auto": ApprovalMode.AUTO,
        "per-story": ApprovalMode.PER_STORY,
        "per-iteration": ApprovalMode.PER_ITERATION,
    }

    ralph_config = RalphConfig(
        max_iterations=args.max_iterations,
        approval_mode=approval_map[args.approval],
        skip_tests=args.skip_tests,
        auto_commit=not args.no_commit,
        prd_path=Path(args.prd),
    )

    try:
        # Initialize all managers and tools
        config_manager = ConfigManager(working_dir)
        config = config_manager.load_config()
        config_manager.ensure_directories()

        session_dir = Path(config.session_dir).expanduser()
        session_manager = SessionManager(session_dir)
        session_manager.create_session(working_directory=str(working_dir))

        mode_manager = ModeManager()
        approval_manager = ApprovalManager(console)
        undo_manager = UndoManager(config.max_undo_history)

        # Ralph runs autonomously - set auto-approve for "auto" approval mode
        if ralph_config.approval_mode == ApprovalMode.AUTO:
            approval_manager.auto_approve_remaining = True

        # Create tools
        file_ops = FileOperations(config, working_dir)
        write_tool = WriteTool(config, working_dir)
        edit_tool = EditTool(config, working_dir)
        bash_tool = BashTool(config, working_dir)
        web_fetch_tool = WebFetchTool(config, working_dir)
        web_search_tool = WebSearchTool(config, working_dir)
        notebook_edit_tool = NotebookEditTool(working_dir)
        ask_user_tool = AskUserTool()
        vlm_tool = VLMTool(config, working_dir)

        # Build runtime suite
        runtime_service = RuntimeService(config_manager, mode_manager)
        runtime_suite = runtime_service.build_suite(
            file_ops=file_ops,
            write_tool=write_tool,
            edit_tool=edit_tool,
            bash_tool=bash_tool,
            web_fetch_tool=web_fetch_tool,
            web_search_tool=web_search_tool,
            notebook_edit_tool=notebook_edit_tool,
            ask_user_tool=ask_user_tool,
            vlm_tool=vlm_tool,
            mcp_manager=None,
        )

        # Create dependencies
        deps = AgentDependencies(
            mode_manager=mode_manager,
            approval_manager=approval_manager,
            undo_manager=undo_manager,
            session_manager=session_manager,
            working_dir=working_dir,
            console=console,
            config=config,
        )

        # Create orchestrator and run
        orchestrator = RalphOrchestrator(
            working_dir=working_dir,
            config=ralph_config,
            console=console,
        )

        success = orchestrator.run(
            swecli_agent=runtime_suite.agents.normal,
            deps=deps,
        )

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        console.print(f"\n[{WARNING}]Interrupted.[/{WARNING}]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[{ERROR}]Error: {e}[/{ERROR}]")
        import traceback

        traceback.print_exc()
        sys.exit(1)


def _handle_status(args: argparse.Namespace, console: Console) -> None:
    """Handle 'ralph status' command.

    Args:
        args: Parsed arguments
        console: Rich console
    """
    from swecli.ralph.models.prd import RalphPRD

    working_dir = Path.cwd()
    prd_path = working_dir / args.prd

    if not prd_path.exists():
        console.print(f"[{WARNING}]No PRD found: {prd_path}[/{WARNING}]")
        console.print("Run 'swecli ralph create \"description\"' to create one.")
        return

    try:
        prd = RalphPRD.load(prd_path)

        # Display as table
        table = Table(title=f"PRD Status: {prd.project}", show_header=True, header_style="bold cyan")
        table.add_column("ID", style="cyan")
        table.add_column("Title")
        table.add_column("Priority", justify="center")
        table.add_column("Status", justify="center")

        for story in sorted(prd.user_stories, key=lambda s: s.priority):
            status = f"[{SUCCESS}]PASS[/{SUCCESS}]" if story.passes else f"[{WARNING}]PENDING[/{WARNING}]"
            table.add_row(story.id, story.title, str(story.priority), status)

        console.print(table)

        # Summary
        total = len(prd.user_stories)
        completed = sum(1 for s in prd.user_stories if s.passes)

        console.print(f"\nBranch: {prd.branch_name}")
        console.print(f"Progress: {completed}/{total} stories complete")

        if prd.is_complete():
            console.print(f"\n[{SUCCESS}]All stories complete![/{SUCCESS}]")
        else:
            next_story = prd.get_next_story()
            if next_story:
                console.print(f"\nNext: [{next_story.id}] {next_story.title}")

    except Exception as e:
        console.print(f"[{ERROR}]Error loading PRD: {e}[/{ERROR}]")
        sys.exit(1)
