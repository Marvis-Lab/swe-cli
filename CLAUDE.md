# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
# Install with dev dependencies
uv venv && uv pip install -e ".[dev]"
source .venv/bin/activate

# Run the CLI
swecli                    # Interactive TUI
swecli -p "prompt"        # Non-interactive single prompt
swecli --continue         # Resume most recent session
swecli run ui             # Web UI

# Code quality
black swecli/ tests/ --line-length 100
ruff check swecli/ tests/ --fix
mypy swecli/

# Tests
uv run pytest                                    # All tests
uv run pytest tests/test_session_manager.py     # Single file
uv run pytest tests/test_foo.py::test_bar       # Single test
uv run pytest --cov=swecli                      # With coverage

# MCP server management
swecli mcp list
swecli mcp add myserver uvx mcp-server-sqlite
swecli mcp enable/disable myserver
```

## Testing Requirements

**CRITICAL - THIS IS A MUST:** When the user asks to "test" any feature or change, you MUST:

1. **Always use OPENAI_API_KEY** - Ensure the environment variable is set and use it for all testing
2. **Run proper unit tests** - Write and execute unit tests with `uv run pytest`
3. **Perform real end-to-end simulation** - Test the actual feature in the running CLI with real API calls

Both unit tests AND end-to-end testing with real simulation are REQUIRED. Never skip either step. Unit tests alone are NOT sufficient. Real API calls must be made to verify changes work correctly.

```bash
# MUST have API key set
export OPENAI_API_KEY="your-key-here"

# Run unit tests
uv run pytest

# Then run real end-to-end testing
python -m swecli
# Execute real commands that exercise the changed code paths
```

Use the exact system prompts from (do not create custom prompts):
- `swecli/core/agents/prompts/templates/main_system_prompt.txt`
- `swecli/core/agents/prompts/templates/planner_system_prompt.txt`
- `swecli/core/agents/prompts/templates/thinking_system_prompt.txt`

## Architecture Overview

```
Entry Point (cli.py)
       ↓
UI Layer (ui_textual/)
  - runner.py: UI lifecycle orchestration
  - chat_app.py: Textual-based TUI
  - ui_callback.py: Event handling
       ↓
Agent Layer (core/agents/)
  - swecli_agent.py: Main ReAct agent (full tool access)
  - planning_agent.py: Plan mode (read-only tools)
  - subagents/: Specialized agents (ask_user, code_explorer, web_clone, web_generator, planner)
       ↓
Runtime Services (core/runtime/)
  - config.py: Hierarchical config loading
  - mode_manager.py: Normal/Plan mode control
  - approval/: Operation approval system
       ↓
Tool Layer (core/context_engineering/tools/)
  - registry.py: Tool discovery & dispatch
  - handlers/: Tool handlers (file, process, web, mcp, thinking)
  - implementations/: Bash, file ops, web tools, symbol tools
       ↓
Persistence (core/context_engineering/history/)
  - session_manager.py: Conversation persistence (~/.opendev/sessions/)
```

## Key Patterns

**ReAct Loop** (`swecli_agent.py`): Agent reasons → decides tool calls → executes → loops until completion (max 10 iterations).

**Dual-Agent System**: SwecliAgent has full tool access; PlanningAgent restricted to read-only tools. Switch via `/mode` or Shift+Tab.

**Dependency Injection** (`models/agent_deps.py`): Core services (mode manager, approval manager, undo manager, session manager) injected into agents via AgentDependencies.

**Tool Registry** (`registry.py`): Tools register with schemas; registry dispatches to specialized handlers. MCP tools integrate dynamically.

**Hierarchical Config**: Priority: `.opendev/settings.json` (project) > `~/.opendev/settings.json` (user) > env vars > defaults.

**Session Storage**: JSON files in `~/.opendev/sessions/` with 8-character session IDs. Sessions auto-save on message add.

## Code Style

- Line length: 100 characters (Black + Ruff)
- Type hints required on public APIs (mypy strict mode)
- Google-style docstrings
