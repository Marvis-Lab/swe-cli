"""Tool schema builders used by SWE-CLI agents."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Sequence, Union


# Read-only tools allowed in PLAN mode for codebase exploration
PLANNING_TOOLS = {
    "read_file",
    "list_files",
    "search",  # Unified: type="text" (ripgrep) or "ast" (ast-grep)
    "fetch_url",
    "web_search",  # Web search is read-only
    "list_processes",
    "get_process_output",
    "read_pdf",  # PDF extraction is read-only
    # Symbol tools (read-only)
    "find_symbol",
    "find_referencing_symbols",
    # MCP tool discovery (read-only)
    "search_tools",
    # Skills (read-only - just loads knowledge into context)
    "invoke_skill",
    # Subagent spawning (subagents handle their own restrictions)
    "spawn_subagent",
    # User interaction (allows asking clarifying questions)
    "ask_user",
    # Task completion (always allowed - agents must signal completion)
    "task_complete",
}


class ToolSchemaBuilder:
    """Assemble tool schemas for NORMAL mode agents."""

    def __init__(
        self,
        tool_registry: Union[Any, None],
        allowed_tools: Union[list[str], None] = None,
    ) -> None:
        """Initialize the tool schema builder.

        Args:
            tool_registry: The tool registry for MCP and task tool schemas
            allowed_tools: Optional list of allowed tool names for filtering.
                          If None, all tools are allowed. Used by subagents
                          to restrict available tools.
        """
        self._tool_registry = tool_registry
        self._allowed_tools = allowed_tools

    def build(self, thinking_visible: bool = True) -> list[dict[str, Any]]:
        """Return tool schema definitions including MCP and task tool extensions.

        Args:
            thinking_visible: Deprecated parameter (kept for API compatibility).
                             Thinking is now a separate pre-processing phase,
                             not a tool the model calls.

        Returns:
            List of tool schemas. If allowed_tools was set, only returns
            schemas for tools in that list.
        """
        # Get all builtin tool schemas
        schemas: list[dict[str, Any]] = deepcopy(_BUILTIN_TOOL_SCHEMAS)

        # Filter to allowed tools if specified
        if self._allowed_tools is not None:
            schemas = [
                schema for schema in schemas if schema["function"]["name"] in self._allowed_tools
            ]

        # Add task tool schema if subagent manager is configured
        # Only add if spawn_subagent is in allowed_tools or no filter
        if self._allowed_tools is None or "spawn_subagent" in self._allowed_tools:
            task_schema = self._build_task_schema()
            if task_schema:
                schemas.append(task_schema)

        # Add MCP tool schemas (only those matching allowed_tools)
        mcp_schemas = self._build_mcp_schemas()
        if mcp_schemas:
            if self._allowed_tools is not None:
                # Filter MCP schemas to only allowed tools
                allowed_set = set(self._allowed_tools)
                mcp_schemas = [
                    schema for schema in mcp_schemas if schema["function"]["name"] in allowed_set
                ]
            schemas.extend(mcp_schemas)
        return schemas

    def _build_task_schema(self) -> dict[str, Any] | None:
        """Build task tool schema with available subagent types."""
        if not self._tool_registry:
            return None

        subagent_manager = getattr(self._tool_registry, "_subagent_manager", None)
        if not subagent_manager:
            return None

        from swecli.core.agents.subagents.task_tool import create_task_tool_schema

        return create_task_tool_schema(subagent_manager)

    def _build_mcp_schemas(self) -> Sequence[dict[str, Any]]:
        """Build MCP tool schemas - only returns discovered tools for token efficiency.

        MCP tools are NOT loaded by default. The agent must use search_tools() to
        discover them first, which adds them to the discovered set.
        """
        if not self._tool_registry or not getattr(self._tool_registry, "mcp_manager", None):
            return []

        # Only return schemas for tools that have been "discovered" via search_tools
        discovered_tools = self._tool_registry.get_discovered_mcp_tools()
        schemas: list[dict[str, Any]] = []
        for tool in discovered_tools:
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("input_schema", {}),
                    },
                }
            )
        return schemas


class PlanningToolSchemaBuilder:
    """Assemble read-only tool schemas for PLAN mode agents.

    Planning agents can explore the codebase but cannot make changes.
    Includes spawn_subagent for asking user questions and other subagent tasks.
    """

    def __init__(self, tool_registry: Union[Any, None] = None) -> None:
        self._tool_registry = tool_registry

    def build(self) -> list[dict[str, Any]]:
        """Return read-only tool schemas including spawn_subagent for planning mode."""
        schemas = [
            deepcopy(schema)
            for schema in _BUILTIN_TOOL_SCHEMAS
            if schema["function"]["name"] in PLANNING_TOOLS
        ]

        # Add spawn_subagent schema (for ask-user and other subagents)
        task_schema = self._build_task_schema()
        if task_schema:
            schemas.append(task_schema)

        return schemas

    def _build_task_schema(self) -> dict[str, Any] | None:
        """Build task tool schema with available subagent types."""
        if not self._tool_registry:
            return None

        subagent_manager = getattr(self._tool_registry, "_subagent_manager", None)
        if not subagent_manager:
            return None

        from swecli.core.agents.subagents.task_tool import create_task_tool_schema

        return create_task_tool_schema(subagent_manager)


_BUILTIN_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file with the specified content. Use this when the user asks to create, write, or save a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path where the file should be created (e.g., 'app.py', 'src/main.js')",
                    },
                    "content": {
                        "type": "string",
                        "description": "The complete content to write to the file",
                    },
                    "create_dirs": {
                        "type": "boolean",
                        "description": "Whether to create parent directories if they don't exist",
                        "default": True,
                    },
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit an existing file by replacing old content with new content. Use this to modify, update, or fix code in existing files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to edit",
                    },
                    "old_content": {
                        "type": "string",
                        "description": "The exact text to find and replace in the file",
                    },
                    "new_content": {
                        "type": "string",
                        "description": "The new text to replace the old content with",
                    },
                    "match_all": {
                        "type": "boolean",
                        "description": "Whether to replace all occurrences (true) or just the first one (false)",
                        "default": False,
                    },
                },
                "required": ["file_path", "old_content", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Use this when you need to see what's in a file before editing it or to answer questions about file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to read",
                    }
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory or search for files matching a pattern. Use this to explore the codebase structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The directory path to list",
                        "default": ".",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Optional glob pattern to filter files (e.g., '*.py', '**/*.js')",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search for patterns in code. Supports two modes: 'text' (default) for regex/string search using ripgrep, and 'ast' for structural code pattern matching using ast-grep. AST mode matches code structure regardless of formatting - use $VAR wildcards to match any AST node.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern. For text mode: regex pattern. For AST mode: structural pattern with $VAR wildcards (e.g., '$A && $A()', 'console.log($MSG)')",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search. Be specific to avoid timeouts.",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["text", "ast"],
                        "description": "Search type: 'text' for regex/string matching (default), 'ast' for structural code patterns",
                        "default": "text",
                    },
                    "lang": {
                        "type": "string",
                        "description": "Language hint for AST mode: python, typescript, javascript, go, rust, java, etc. Auto-detected if not specified.",
                    },
                },
                "required": ["pattern", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute any bash/shell command. Use this whenever the user asks you to run a command. Commands are subject to safety checks and may require approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute",
                    },
                    "background": {
                        "type": "boolean",
                        "description": "Run command in background (returns immediately with PID). Use for long-running commands like servers.",
                        "default": False,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_processes",
            "description": "List all running background processes started by run_command with background=true.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_process_output",
            "description": "Get output from a background process. Returns stdout, stderr, status, and exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "integer",
                        "description": "Process ID returned by run_command with background=true",
                    },
                },
                "required": ["pid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kill_process",
            "description": "Kill a background process. Use signal 15 (SIGTERM) for graceful shutdown, or 9 (SIGKILL) to force kill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "integer",
                        "description": "Process ID to kill",
                    },
                    "signal": {
                        "type": "integer",
                        "description": "Signal to send (15=SIGTERM, 9=SIGKILL)",
                        "default": 15,
                    },
                },
                "required": ["pid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch content from a URL or perform a deep crawl across linked pages. Useful for reading documentation, APIs, or entire site sections. Automatically extracts text from HTML.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch (must start with http:// or https://)",
                    },
                    "extract_text": {
                        "type": "boolean",
                        "description": "Whether to extract text from HTML (default: true)",
                        "default": True,
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Maximum content length in characters (default: 50000)",
                        "default": 50000,
                    },
                    "deep_crawl": {
                        "type": "boolean",
                        "description": "Follow links and crawl multiple pages starting from the seed URL.",
                        "default": False,
                    },
                    "crawl_strategy": {
                        "type": "string",
                        "enum": ["bfs", "dfs", "best_first"],
                        "description": "Traversal strategy when deep_crawl is true. best_first (default) prioritizes relevance, bfs covers broadly, dfs follows a single branch.",
                        "default": "best_first",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum depth (beyond the seed page) to crawl when deep_crawl is enabled. Depth 0 is the starting page. Defaults to 1.",
                        "default": 1,
                    },
                    "include_external": {
                        "type": "boolean",
                        "description": "Allow crawling links that leave the starting domain when deep_crawl is enabled.",
                        "default": False,
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "Optional cap on the total number of pages to crawl when deep_crawl is enabled.",
                    },
                    "allowed_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional allow-list of domains to keep while deep crawling.",
                    },
                    "blocked_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional block-list of domains to skip while deep crawling.",
                    },
                    "url_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional glob-style URL patterns the crawler must match (e.g., '*docs*').",
                    },
                    "stream": {
                        "type": "boolean",
                        "description": "When true (and deep_crawl is enabled) stream pages as they are discovered before aggregation.",
                        "default": False,
                    },
                },
                "required": ["url"],
            },
        },
    },
    # ===== Web Search Tool =====
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information using DuckDuckGo. Returns results with titles, URLs, and snippets. Use this for finding up-to-date information, documentation, tutorials, and answers to questions. Results are formatted as markdown links for easy reference. You MUST include a 'Sources:' section at the end of your response listing the URLs used.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to use. Be specific and include relevant keywords.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 10)",
                        "default": 10,
                    },
                    "allowed_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Only include search results from these domains (e.g., ['docs.python.org', 'stackoverflow.com'])",
                    },
                    "blocked_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Never include search results from these domains",
                    },
                },
                "required": ["query"],
            },
        },
    },
    # ===== Notebook Edit Tool =====
    {
        "type": "function",
        "function": {
            "name": "notebook_edit",
            "description": "Edit cells in a Jupyter notebook (.ipynb file). Supports replacing cell content, inserting new cells, and deleting cells. Cells can be identified by cell_id or cell_number (0-indexed). For insert mode, the new cell is inserted after the specified cell or at the given position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "notebook_path": {
                        "type": "string",
                        "description": "Absolute path to the Jupyter notebook file (.ipynb)",
                    },
                    "new_source": {
                        "type": "string",
                        "description": "New source content for the cell. Required for replace and insert modes.",
                    },
                    "cell_id": {
                        "type": "string",
                        "description": "ID of the cell to edit. For insert mode, new cell is inserted after this cell.",
                    },
                    "cell_number": {
                        "type": "integer",
                        "description": "0-indexed cell position. Alternative to cell_id. For insert mode, new cell is inserted at this position.",
                    },
                    "cell_type": {
                        "type": "string",
                        "enum": ["code", "markdown"],
                        "description": "Cell type. Required for insert mode, optional for replace mode.",
                    },
                    "edit_mode": {
                        "type": "string",
                        "enum": ["replace", "insert", "delete"],
                        "default": "replace",
                        "description": "Operation type: replace (update existing cell), insert (add new cell), or delete (remove cell).",
                    },
                },
                "required": ["notebook_path", "new_source"],
            },
        },
    },
    # ===== Ask User Question Tool =====
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user structured questions with multiple-choice options. Use this when you need to gather user preferences, clarify requirements, get decisions on implementation choices, or offer choices about direction. Users can select from predefined options or provide custom 'Other' input. Supports 1-4 questions with 2-4 options each.",
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "description": "List of questions to ask (1-4 questions)",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {
                                    "type": "string",
                                    "description": "The complete question to ask. Should be clear and end with a question mark.",
                                },
                                "header": {
                                    "type": "string",
                                    "description": "Short label displayed as a chip/tag (max 12 chars). E.g., 'Auth method', 'Library'.",
                                    "maxLength": 12,
                                },
                                "options": {
                                    "type": "array",
                                    "description": "Available choices (2-4 options). An 'Other' option is added automatically.",
                                    "minItems": 2,
                                    "maxItems": 4,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": {
                                                "type": "string",
                                                "description": "Display text for the option (1-5 words).",
                                            },
                                            "description": {
                                                "type": "string",
                                                "description": "Explanation of what this option means or implies.",
                                            },
                                        },
                                        "required": ["label", "description"],
                                    },
                                },
                                "multiSelect": {
                                    "type": "boolean",
                                    "default": False,
                                    "description": "If true, allow selecting multiple options instead of just one.",
                                },
                            },
                            "required": ["question", "header", "options"],
                        },
                    },
                },
                "required": ["questions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_todos",
            "description": "Create a todo list at the START of a complex task. Write 4-7 todo items that break down the work into steps. Each todo has 'content' (task description) and 'activeForm' (present continuous like 'Creating files'). Use 'pending' status for all initial items. REPLACES the entire todo list - call once at the beginning, then use update_todo to change status as you work.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "List of todo items to create",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {
                                    "type": "string",
                                    "description": "The task description",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": "Task status. Defaults to 'pending'.",
                                    "default": "pending",
                                },
                                "activeForm": {
                                    "type": "string",
                                    "description": "Present continuous form shown during execution (e.g., 'Running tests')",
                                },
                            },
                            "required": ["content"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_todo",
            "description": "Update an existing todo's status as you work. Set status to 'in_progress' when starting a task, 'completed' when finished. Use the todo ID (e.g., 'todo-1' or just '1'). This is how you track progress through your plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "ID of the to-do to update (shown in the panel).",
                    },
                    "title": {
                        "type": "string",
                        "description": "New title for this to-do item.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["todo", "doing", "done"],
                        "description": "Set to 'doing' when you start, 'done' when you finish.",
                    },
                    "log": {
                        "type": "string",
                        "description": "Append a log entry while working on this task.",
                    },
                    "expanded": {
                        "type": "boolean",
                        "description": "Show or hide logs beneath this to-do.",
                    },
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_todo",
            "description": "Mark a to-do item as done and optionally append a final log entry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "ID of the to-do item to mark complete.",
                    },
                    "log": {
                        "type": "string",
                        "description": "Optional completion note.",
                    },
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": "Render the current to-do panel inside the console output.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_browser",
            "description": "Opens a URL or local file in the user's default web browser. Useful for showing web applications during development (e.g., 'open http://localhost:3000' or 'open index.html'). Automatically handles localhost URLs and converts local file paths to file:// URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL or file path to open in the browser. Supports: full URLs (http://example.com), localhost addresses (localhost:3000), and local file paths (index.html, ./app.html, /path/to/file.html). Local files are automatically converted to file:// URLs.",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_screenshot",
            "description": "Capture a screenshot and save it to a temporary location. The user can then reference this screenshot in their queries by mentioning the file path. Useful when the user wants to discuss or analyze a screenshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "monitor": {
                        "type": "integer",
                        "description": "Monitor number to capture (default: 1 for primary monitor)",
                        "default": 1,
                    },
                    "region": {
                        "type": "object",
                        "description": "Optional region to capture (x, y, width, height). If not provided, captures full screen.",
                        "properties": {
                            "x": {"type": "integer", "description": "X coordinate"},
                            "y": {"type": "integer", "description": "Y coordinate"},
                            "width": {"type": "integer", "description": "Width in pixels"},
                            "height": {"type": "integer", "description": "Height in pixels"},
                        },
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_image",
            "description": "Analyze an image using the configured Vision Language Model (VLM). Supports both local image files and online URLs. Only available if user has configured a VLM model via /models command. Use this when user asks to analyze, describe, or extract information from images.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Text prompt describing what to analyze in the image (e.g., 'Describe this image', 'What errors do you see?', 'Extract text from this image')",
                    },
                    "image_path": {
                        "type": "string",
                        "description": "Path to local image file (relative to working directory or absolute). Supports .jpg, .jpeg, .png, .gif, .webp. Takes precedence over image_url if both provided.",
                    },
                    "image_url": {
                        "type": "string",
                        "description": "URL of online image (must start with http:// or https://). Used only if image_path not provided.",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Maximum tokens in response (optional, defaults to config value)",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_web_screenshot",
            "description": "Capture a full-page screenshot (and optionally PDF) of a web page using Crawl4AI. Uses advanced web crawling with Playwright under the hood. Waits for page load, handles dynamic content, and captures full scrollable pages reliably. More robust than Playwright alone for complex pages. Use this when user wants to screenshot a website or web application.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the web page to capture (must start with http:// or https://)",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional path to save screenshot (relative to working directory or absolute). If not provided, auto-generates filename in temp directory. For PDF, the .pdf extension will be automatically used.",
                    },
                    "capture_pdf": {
                        "type": "boolean",
                        "description": "If true, also capture a PDF version of the page. PDF is more reliable for very long pages. Both screenshot and PDF will be saved if enabled. Default: false",
                        "default": False,
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Maximum time to wait for page load in milliseconds. Default: 90000 (90 seconds). Complex sites with heavy JavaScript (like SaaS platforms, dashboards) may need 120000-180000ms.",
                        "default": 90000,
                    },
                    "viewport_width": {
                        "type": "integer",
                        "description": "Browser viewport width in pixels. Default: 1920",
                        "default": 1920,
                    },
                    "viewport_height": {
                        "type": "integer",
                        "description": "Browser viewport height in pixels. Default: 1080",
                        "default": 1080,
                    },
                },
                "required": ["url"],
            },
        },
    },
    # ===== PDF Tool =====
    {
        "type": "function",
        "function": {
            "name": "read_pdf",
            "description": "Extract text content from a PDF file (academic papers, documentation). Returns full text with page markers, detected sections (Abstract, Introduction, etc.), and metadata (title, author). Best for reading research papers to understand methodology and implement code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the PDF file (absolute or relative to working directory)",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    # ===== Symbol Tools (LSP-based) =====
    {
        "type": "function",
        "function": {
            "name": "find_symbol",
            "description": "Find symbols (functions, classes, variables, etc.) by name using LSP. Supports name path patterns like 'MyClass.method', partial matches like 'method', or wildcards like 'My*'. Returns symbol locations with file, line, and kind information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Name path pattern to search for. Examples: 'MyClass' (class), 'MyClass.method' (method in class), 'my_func' (function), 'My*' (wildcard)",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Optional file path to limit search scope. If not provided, searches the workspace.",
                    },
                },
                "required": ["symbol_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_referencing_symbols",
            "description": "Find all code locations that reference a specific symbol. Useful for understanding how a function, class, or variable is used throughout the codebase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Name of the symbol to find references for",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to file where the symbol is defined (required to locate the symbol)",
                    },
                    "include_declaration": {
                        "type": "boolean",
                        "description": "Whether to include the declaration itself in results",
                        "default": True,
                    },
                },
                "required": ["symbol_name", "file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_before_symbol",
            "description": "Insert code immediately before a symbol (function, class, etc.). The content is inserted at the same indentation level as the symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Name of the symbol to insert before",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to file containing the symbol",
                    },
                    "content": {
                        "type": "string",
                        "description": "Code content to insert",
                    },
                },
                "required": ["symbol_name", "file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_after_symbol",
            "description": "Insert code immediately after a symbol (function, class, etc.). The content is inserted at the same indentation level as the symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Name of the symbol to insert after",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to file containing the symbol",
                    },
                    "content": {
                        "type": "string",
                        "description": "Code content to insert",
                    },
                },
                "required": ["symbol_name", "file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_symbol_body",
            "description": "Replace the body of a symbol (function, method, class) with new content. By default preserves the signature for functions/methods.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Name of the symbol whose body to replace",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to file containing the symbol",
                    },
                    "new_body": {
                        "type": "string",
                        "description": "New body content for the symbol",
                    },
                    "preserve_signature": {
                        "type": "boolean",
                        "description": "Whether to keep the function/method signature (default: true)",
                        "default": True,
                    },
                },
                "required": ["symbol_name", "file_path", "new_body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_symbol",
            "description": "Rename a symbol across the entire codebase using LSP refactoring. This is a safe rename that updates all references to the symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Current name of the symbol to rename",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to file where symbol is defined",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New name for the symbol",
                    },
                },
                "required": ["symbol_name", "file_path", "new_name"],
            },
        },
    },
    # ===== Task Completion Tool =====
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "Call this tool when you have completed the user's request. You MUST call this tool to end the conversation - do NOT just stop making tool calls. Provide a summary of what was accomplished.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary of what was accomplished. Be concise but complete.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["success", "partial", "failed"],
                        "description": "Completion status: 'success' if fully completed, 'partial' if some parts done, 'failed' if couldn't complete",
                        "default": "success",
                    },
                },
                "required": ["summary", "status"],
            },
        },
    },
    # MCP Tool Discovery (Token-Efficient)
    {
        "type": "function",
        "function": {
            "name": "search_tools",
            "description": "Search for available MCP tools from connected servers. Use this to discover tools before using them. MCP tool schemas are NOT loaded by default to save context tokens - you must search for them first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query - matches tool names and descriptions. Use '*' or empty string to list all tools.",
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["names", "brief", "full"],
                        "description": "Level of detail: 'names' (tool names only), 'brief' (names + one-line descriptions), 'full' (complete schemas including parameters)",
                        "default": "brief",
                    },
                    "server": {
                        "type": "string",
                        "description": "Optional: filter to specific MCP server name",
                    },
                },
                "required": ["query"],
            },
        },
    },
    # Skills System Tool
    {
        "type": "function",
        "function": {
            "name": "invoke_skill",
            "description": "Load a skill's knowledge and instructions into the current conversation context. Skills provide specialized expertise without spawning a separate agent. Use this when you need domain knowledge (coding conventions, best practices, specific tool guidance). Call without skill_name to list available skills.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Name of the skill to invoke. Can include namespace prefix (e.g., 'git:commit'). Leave empty to list available skills.",
                    },
                },
                "required": [],
            },
        },
    },
    # MCP Configuration Tools
    {
        "type": "function",
        "function": {
            "name": "configure_mcp_server",
            "description": "Configure an MCP (Model Context Protocol) server from a preset. Use this when user asks to set up integrations like GitHub, database connections, or other MCP servers. This will add the server to ~/.swecli/mcp.json and optionally connect to it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "preset_name": {
                        "type": "string",
                        "description": "Name of the preset to configure. Available presets: github, filesystem, postgres, sqlite, memory, fetch, brave-search, puppeteer, slack, gdrive, git, sequential-thinking",
                    },
                    "server_name": {
                        "type": "string",
                        "description": "Optional custom name for this server instance. Defaults to the preset name.",
                    },
                    "auto_connect": {
                        "type": "boolean",
                        "description": "Whether to connect to the server immediately after configuring. Default: true",
                        "default": True,
                    },
                },
                "required": ["preset_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_mcp_presets",
            "description": "List available MCP server presets that can be configured. Use this to show the user what integrations are available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category to filter by (e.g., 'development', 'database', 'web', 'communication')",
                    },
                    "search": {
                        "type": "string",
                        "description": "Optional search query to find presets by name or description",
                    },
                },
                "required": [],
            },
        },
    },
    # ===== Task Output Tool =====
    {
        "type": "function",
        "function": {
            "name": "get_subagent_output",
            "description": "ONLY use this for subagents launched with run_in_background=true. "
            "Synchronous subagents (the default) return results immediately in the tool response with "
            "[completion_status=success] - do NOT call this tool for them. "
            "The tool_call_id from spawn_subagent is NOT a task_id - only background subagents return task_ids.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task_id returned when a background subagent was spawned (NOT the tool_call_id). "
                        "Only subagents with run_in_background=true return a task_id.",
                    },
                    "block": {
                        "type": "boolean",
                        "description": "Whether to wait for completion. Set to false for non-blocking status check.",
                        "default": True,
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum wait time in milliseconds (max 600000)",
                        "default": 30000,
                        "maximum": 600000,
                    },
                },
                "required": ["task_id"],
            },
        },
    },
]
