# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SWE-CLI is an AI-powered CLI coding agent that supports MCP (Model Context Protocol), multi-provider LLMs (Anthropic, OpenAI, Fireworks), and codebase understanding through a modular SOLID-based architecture.

## Development Commands

```bash
# Install in development mode
uv venv && uv pip install -e ".[dev]"

# Run the application
uv run swecli                          # Start interactive TUI
uv run swecli -p "create hello.py"     # Non-interactive mode
uv run swecli run ui                   # Start web UI

# Run tests
uv run pytest                          # All tests
uv run pytest tests/test_session_manager.py  # Single file
uv run pytest -v                       # Verbose output
uv run pytest --cov=swecli             # With coverage

# Code quality
black swecli/ --line-length 100        # Format
ruff check swecli/                     # Lint
mypy swecli/                           # Type check
```

## Architecture Overview

### Entry Points
- `swecli/cli.py` - Main CLI entry point, argument parsing, command routing
- `swecli/ui_textual/runner.py` - Launches the Textual-based TUI
- `swecli/ui_textual/chat_app.py` - Main Textual chat application

### Core Layer (`swecli/core/`)

**Agents (`core/agents/`)**
- `SwecliAgent` - Primary agent for interactive sessions using ReAct pattern
- Uses component-based design: HTTP client, response processing, system prompts, tool schemas
- Subagents in `core/agents/subagents/agents/` for specialized tasks (code review, test writing, web generation)

**Base Classes (`core/base/`)**
- `abstract/` - BaseAgent, BaseTool, BaseManager, BaseMonitor
- `interfaces/` - ToolRegistryInterface, SessionInterface, AgentInterface
- `factories/` - AgentFactory, ToolFactory

**Runtime (`core/runtime/`)**
- `ConfigManager` - Configuration loading from ~/.swecli/settings.json and project config
- `ModeManager` - Dual modes: NORMAL (full execution) and PLAN (read-only)
- `approval/` - Operation approval with auto-approval rules

**Context Engineering (`core/context_engineering/`)**
- `tools/registry.py` - Tool dispatcher coordinating all handlers
- `tools/handlers/` - FileToolHandler, ProcessToolHandler, WebToolHandler, etc.
- `tools/implementations/` - BashTool, EditTool, WriteTool, WebFetchTool, etc.
- `tools/lsp/` - Language Server Protocol integration (20+ language servers)
- `history/` - SessionManager, UndoManager
- `mcp/` - MCP server configuration, lifecycle, and tool integration

### UI Layer (`swecli/ui_textual/`)
- `widgets/` - ConversationLog, ChatTextArea, StatusBar, TodoPanel
- `controllers/` - ApprovalPromptController, CommandRouter, SpinnerController
- `formatters_internal/` - Output formatting (bash, markdown, file operations)

### REPL Layer (`swecli/repl/`)
- `repl.py` - Interactive loop orchestration (prompt_toolkit based)
- `query_processor.py` - User query handling and agent coordination
- `commands/` - Slash command handlers (session, mode, MCP, help)

## Key Patterns

### ReAct Loop
The agent uses iterative Reason+Act:
1. User query → Agent reasons about task → Tool calls
2. Tools execute (with approval if needed)
3. Results added to message history
4. Loop continues until task completion

### Tool Registry Pattern
Tools register with schemas and execute via `ToolRegistry.execute_tool()`. The registry:
- Routes to appropriate handlers (file, process, web, MCP)
- Enforces plan mode restrictions (only read-only tools in PLAN mode)
- Manages approval flow

### Dual Mode System
- **NORMAL mode**: Full tool access for code execution
- **PLAN mode**: Read-only tools only (read_file, search, fetch_url, etc.)
- Switch with `/mode` command or Shift+Tab

### MCP Integration
MCP servers extend the tool registry dynamically:
- Servers configured via `swecli mcp add/remove/enable/disable`
- Tools prefixed with `mcp__<servername>__<toolname>`
- Async lifecycle management in `mcp/manager.py`

## Configuration

Configuration loads from (in order of precedence):
1. `~/.swecli/settings.json` - Global settings
2. `.swecli/config.json` - Project-specific
3. Environment variables (`$FIREWORKS_API_KEY`, etc.)

Sessions stored in `~/.swecli/sessions/` as JSON.

## Testing

Tests in `tests/` cover:
- Session management, context compaction
- Tool execution, interrupt handling
- UI components (Textual widgets, autocomplete)
- MCP integration

Run specific test patterns:
```bash
uv run pytest -k "session"    # Run tests matching "session"
uv run pytest -x              # Stop on first failure
```

## Recent Changes

### Approval Modal Tool Header Fix (2026-01-12)
**Status:** Completed and pushed to `feat/conversation-log-v2-text-selection`

**Problem:** Tool header (`⏺ Run (python app.py)`) wasn't appearing above the approval panel for bash commands.

**Root Cause:** `add_tool_call()` failed silently in Textual workers because `call_from_thread()` throws `RuntimeError` when already on main thread (Textual workers use async scheduling on same thread).

**Solution:** Mount tool header directly in `render_approval_prompt()` with `.tool-header` CSS class (instead of `.approval-prompt`) so it persists after approval panel is cleared.

**Files Modified:**
- `swecli/ui_textual/widgets/conversation_log_v2.py` - Added `persistent_header` param
- `swecli/ui_textual/widgets/conversation_log.py` - V1 compatibility
- `swecli/ui_textual/controllers/approval_prompt_controller.py` - Build and pass tool header
- `swecli/ui_textual/managers/approval_manager.py` - Cleaned up debug logging
