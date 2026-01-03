"""Primary tool registry implementation coordinating handlers."""

from __future__ import annotations

from typing import Any, Union

from swecli.core.runtime import OperationMode
from swecli.core.context_engineering.tools.context import ToolExecutionContext
from swecli.core.context_engineering.tools.handlers.file_handlers import FileToolHandler
from swecli.core.context_engineering.mcp.handler import McpToolHandler
from swecli.core.context_engineering.tools.handlers.process_handlers import ProcessToolHandler
from swecli.core.context_engineering.tools.handlers.web_handlers import WebToolHandler
from swecli.core.context_engineering.tools.handlers.screenshot_handler import ScreenshotToolHandler
from swecli.core.context_engineering.tools.handlers.todo_handler import TodoHandler
from swecli.core.context_engineering.tools.handlers.mcp_config_handler import MCPConfigHandler
from swecli.core.context_engineering.tools.implementations.pdf_tool import PDFTool
from swecli.core.context_engineering.tools.symbol_tools import (
    handle_find_symbol,
    handle_find_referencing_symbols,
    handle_insert_before_symbol,
    handle_insert_after_symbol,
    handle_replace_symbol_body,
    handle_rename_symbol,
)

_PLAN_READ_ONLY_TOOLS = {
    "read_file",
    "list_files",
    "search",  # Unified search: text (ripgrep) and AST (ast-grep) modes
    "fetch_url",
    "list_processes",
    "get_process_output",
    "list_screenshots",
    "analyze_image",  # VLM is read-only, safe for planning mode
    "read_pdf",  # PDF extraction is read-only
    # Symbol tools (read-only)
    "find_symbol",
    "find_referencing_symbols",
    # Subagent spawning allowed in plan mode (subagents handle their own restrictions)
    "spawn_subagent",
}


class ToolRegistry:
    """Dispatches tool invocations to dedicated handlers."""

    def __init__(
        self,
        file_ops: Union[Any, None] = None,
        write_tool: Union[Any, None] = None,
        edit_tool: Union[Any, None] = None,
        bash_tool: Union[Any, None] = None,
        web_fetch_tool: Union[Any, None] = None,
        open_browser_tool: Union[Any, None] = None,
        vlm_tool: Union[Any, None] = None,
        web_screenshot_tool: Union[Any, None] = None,
        mcp_manager: Union[Any, None] = None
    ) -> None:
        self.file_ops = file_ops
        self.write_tool = write_tool
        self.edit_tool = edit_tool
        self.bash_tool = bash_tool
        self.web_fetch_tool = web_fetch_tool
        self.open_browser_tool = open_browser_tool
        self.vlm_tool = vlm_tool
        self.web_screenshot_tool = web_screenshot_tool

        self._file_handler = FileToolHandler(file_ops, write_tool, edit_tool)
        self._process_handler = ProcessToolHandler(bash_tool)
        self._web_handler = WebToolHandler(web_fetch_tool)
        self._mcp_handler = McpToolHandler(mcp_manager)
        self._mcp_config_handler = MCPConfigHandler(mcp_manager)
        self._screenshot_handler = ScreenshotToolHandler()
        self.todo_handler = TodoHandler()
        self._pdf_tool = PDFTool()
        self._subagent_manager: Union[Any, None] = None
        self.set_mcp_manager(mcp_manager)

        self._handlers: dict[str, Any] = {
            "write_file": self._file_handler.write_file,
            "edit_file": self._file_handler.edit_file,
            "read_file": self._file_handler.read_file,
            "list_files": self._file_handler.list_files,
            "search": self._file_handler.search,  # Unified: type="text" (default) or "ast"
            "run_command": self._process_handler.run_command,
            "list_processes": lambda args, ctx: self._process_handler.list_processes(),
            "get_process_output": self._process_handler.get_process_output,
            "kill_process": self._process_handler.kill_process,
            "fetch_url": self._web_handler.fetch_url,
            "open_browser": self._open_browser,
            "capture_screenshot": self._screenshot_handler.capture_screenshot,
            "list_screenshots": lambda args: self._screenshot_handler.list_screenshots(),
            "clear_screenshots": self._screenshot_handler.clear_screenshots,
            "analyze_image": self._analyze_image,
            "capture_web_screenshot": self._capture_web_screenshot,
            "list_web_screenshots": lambda args: self._list_web_screenshots(),
            "clear_web_screenshots": self._clear_web_screenshots,
            "write_todos": self._write_todos,
            "update_todo": self._update_todo,
            "complete_todo": self._complete_todo,
            "list_todos": lambda args, ctx=None: self.todo_handler.list_todos(),
            # Symbol tools (LSP-based)
            "find_symbol": lambda args: handle_find_symbol(args),
            "find_referencing_symbols": lambda args: handle_find_referencing_symbols(args),
            "insert_before_symbol": lambda args: handle_insert_before_symbol(args),
            "insert_after_symbol": lambda args: handle_insert_after_symbol(args),
            "replace_symbol_body": lambda args: handle_replace_symbol_body(args),
            "rename_symbol": lambda args: handle_rename_symbol(args),
            # Subagent spawning tool
            "spawn_subagent": self._execute_spawn_subagent,
            # PDF extraction tool
            "read_pdf": self._read_pdf,
            # MCP configuration tools
            "configure_mcp_server": self._mcp_config_handler.configure_mcp_server,
            "list_mcp_presets": self._mcp_config_handler.list_mcp_presets,
        }

    def set_subagent_manager(self, manager: Any) -> None:
        """Set the subagent manager for task tool execution.

        Args:
            manager: SubAgentManager instance
        """
        self._subagent_manager = manager

    def get_subagent_manager(self) -> Union[Any, None]:
        """Get the subagent manager.

        Returns:
            SubAgentManager instance or None
        """
        return self._subagent_manager

    def _execute_spawn_subagent(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Execute the spawn_subagent tool to spawn a subagent.

        Args:
            arguments: Tool arguments with 'description' and 'subagent_type'
            context: Tool execution context

        Returns:
            Result from subagent execution
        """
        if not self._subagent_manager:
            return {
                "success": False,
                "error": "SubAgentManager not configured. spawn_subagent tool unavailable.",
                "output": None,
            }

        description = arguments.get("description", "")
        subagent_type = arguments.get("subagent_type", "general-purpose")

        if not description:
            return {
                "success": False,
                "error": "Task description is required for spawn_subagent",
                "output": None,
            }

        # Create deps from context
        from swecli.core.agents.subagents.manager import SubAgentDeps

        deps = SubAgentDeps(
            mode_manager=context.mode_manager if context else None,
            approval_manager=context.approval_manager if context else None,
            undo_manager=context.undo_manager if context else None,
        )

        # Get ui_callback from context for nested tool call display
        ui_callback = context.ui_callback if context else None

        # Get task_monitor from context for interrupt support
        task_monitor = context.task_monitor if context else None

        # show_spawn_header=False because react_executor already showed the Spawn[] header
        # via on_tool_call before calling this tool handler
        result = self._subagent_manager.execute_subagent(
            name=subagent_type,
            task=description,
            deps=deps,
            ui_callback=ui_callback,
            task_monitor=task_monitor,
            show_spawn_header=False,
        )

        # Format output for consistency
        if result.get("success"):
            content = result.get("content", "")
            return {
                "success": True,
                "output": None,  # Don't show in tool result line
                "separate_response": content,  # Show as separate assistant message
                "subagent_type": subagent_type,
            }
        else:
            # Check both "error" and "content" fields for error message
            # SwecliAgent.run_sync() puts errors in "content", not "error"
            error = result.get("error") or result.get("content") or "Unknown error"
            return {
                "success": False,
                "error": f"[{subagent_type}] {error}",
                "output": None,
                "interrupted": result.get("interrupted", False),  # Propagate interrupt flag
            }

    def get_schemas(self) -> list[dict[str, Any]]:
        """Compatibility hook (schemas generated elsewhere)."""
        return []

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        mode_manager: Union[Any, None] = None,
        approval_manager: Union[Any, None] = None,
        undo_manager: Union[Any, None] = None,
        task_monitor: Union[Any, None] = None,
        session_manager: Union[Any, None] = None,
        ui_callback: Union[Any, None] = None,
        is_subagent: bool = False,
    ) -> dict[str, Any]:
        """Execute a tool by delegating to registered handlers."""
        if tool_name.startswith("mcp__"):
            return self._mcp_handler.execute(tool_name, arguments)

        if tool_name not in self._handlers:
            return {"success": False, "error": f"Unknown tool: {tool_name}", "output": None}

        context = ToolExecutionContext(
            mode_manager=mode_manager,
            approval_manager=approval_manager,
            undo_manager=undo_manager,
            task_monitor=task_monitor,
            session_manager=session_manager,
            ui_callback=ui_callback,
            is_subagent=is_subagent,
        )

        if self._is_plan_blocked(tool_name, context):
            return self._plan_blocked_result(tool_name, arguments)

        handler = self._handlers[tool_name]
        try:
            if tool_name in {"write_file", "edit_file", "run_command", "spawn_subagent"}:
                # Handlers requiring context
                return handler(arguments, context)

            if tool_name == "list_processes":
                return handler(arguments, context)

            if tool_name in {"get_process_output", "kill_process"}:
                return handler(arguments)

            # Remaining handlers ignore execution context
            return handler(arguments)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc), "output": None}

    @staticmethod
    def _plan_blocked_result(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        summary_text = (
            f"Plan-only mode blocks '{tool_name}'. Switch to normal mode to execute."
        )
        return {
            "success": False,
            "error": summary_text,
            "plan_only": True,
            "tool_name": tool_name,
            "arguments": arguments,
            "plan_summary": summary_text,
        }

    @staticmethod
    def _is_plan_blocked(tool_name: str, context: ToolExecutionContext) -> bool:
        mode_manager = context.mode_manager
        if not mode_manager:
            return False

        if getattr(mode_manager, "current_mode", None) != OperationMode.PLAN:
            return False

        return tool_name not in _PLAN_READ_ONLY_TOOLS

    def set_mcp_manager(self, mcp_manager: Union[Any, None]) -> None:
        """Update the MCP manager and refresh the handlers."""
        self.mcp_manager = mcp_manager
        self._mcp_handler = McpToolHandler(mcp_manager)
        self._mcp_config_handler.set_mcp_manager(mcp_manager)

    def _open_browser(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the open_browser tool."""
        if not self.open_browser_tool:
            return {
                "success": False,
                "error": "open_browser tool not available",
                "output": None,
            }
        return self.open_browser_tool.execute(**arguments)

    def _analyze_image(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the analyze_image tool (VLM)."""
        if not self.vlm_tool:
            return {
                "success": False,
                "error": "VLM tool not available",
                "output": None,
            }
        result = self.vlm_tool.analyze_image(**arguments)
        # Format output for consistency with other tools
        if result.get("success"):
            return {
                "success": True,
                "output": result.get("content", ""),
                "model": result.get("model"),
                "provider": result.get("provider"),
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "output": None,
            }

    def _capture_web_screenshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the capture_web_screenshot tool."""
        if not self.web_screenshot_tool:
            return {
                "success": False,
                "error": "Web screenshot tool not available",
                "output": None,
            }
        result = self.web_screenshot_tool.capture_web_screenshot(**arguments)
        # Format output for consistency
        if result.get("success"):
            output_lines = [
                f"Screenshot captured: {result.get('screenshot_path')}",
                f"URL: {result.get('url')}",
            ]
            if result.get("pdf_path"):
                output_lines.append(f"PDF captured: {result.get('pdf_path')}")
            if result.get("warning"):
                output_lines.append(f"Warning: {result['warning']}")
            if result.get("pdf_warning"):
                output_lines.append(f"PDF Warning: {result['pdf_warning']}")

            response = {
                "success": True,
                "output": "\n".join(output_lines),
                "screenshot_path": result.get("screenshot_path"),
            }
            if result.get("pdf_path"):
                response["pdf_path"] = result.get("pdf_path")
            return response
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "output": None,
            }

    def _list_web_screenshots(self) -> dict[str, Any]:
        """Execute the list_web_screenshots tool."""
        if not self.web_screenshot_tool:
            return {
                "success": False,
                "error": "Web screenshot tool not available",
                "output": None,
            }
        result = self.web_screenshot_tool.list_web_screenshots()
        if result.get("success"):
            screenshots = result.get("screenshots", [])
            if screenshots:
                output_lines = [f"Found {len(screenshots)} web screenshot(s):"]
                for ss in screenshots:
                    output_lines.append(f"  - {ss['name']} ({ss['size_kb']} KB)")
                output_lines.append(f"\nDirectory: {result.get('directory')}")
            else:
                output_lines = ["No web screenshots found"]
            return {
                "success": True,
                "output": "\n".join(output_lines),
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "output": None,
            }

    def _clear_web_screenshots(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the clear_web_screenshots tool."""
        if not self.web_screenshot_tool:
            return {
                "success": False,
                "error": "Web screenshot tool not available",
                "output": None,
            }
        result = self.web_screenshot_tool.clear_web_screenshots(**arguments)
        if result.get("success"):
            deleted = result.get("deleted_count", 0)
            kept = result.get("kept_count", 0)
            output = f"Deleted {deleted} old screenshot(s), kept {kept} recent"
            return {
                "success": True,
                "output": output,
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "output": None,
            }

    def _write_todos(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Execute the write_todos tool."""
        return self.todo_handler.write_todos(arguments.get("todos", []))

    def _update_todo(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Execute the update_todo tool."""
        return self.todo_handler.update_todo(
            id=arguments.get("id"),
            status=arguments.get("status"),
            title=arguments.get("title"),
        )

    def _complete_todo(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Execute the complete_todo tool."""
        return self.todo_handler.complete_todo(id=arguments.get("id"))

    def _read_pdf(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the read_pdf tool to extract text from a PDF file.

        Args:
            arguments: Dict with 'file_path' key

        Returns:
            Result with extracted text content and metadata
        """
        file_path = arguments.get("file_path", "")
        if not file_path:
            return {
                "success": False,
                "error": "file_path is required for read_pdf",
                "output": None,
            }

        result = self._pdf_tool.extract_text(file_path)

        if result.get("success"):
            # Format output for display
            content = result.get("content", "")
            metadata = result.get("metadata", {})
            page_count = result.get("page_count", 0)
            sections = result.get("sections", [])

            output_parts = []
            if metadata:
                if metadata.get("title"):
                    output_parts.append(f"Title: {metadata['title']}")
                if metadata.get("author"):
                    output_parts.append(f"Author: {metadata['author']}")
            output_parts.append(f"Pages: {page_count}")
            if sections:
                output_parts.append(f"Detected sections: {len(sections)}")
                section_titles = [s.get('title', '') for s in sections[:10]]
                output_parts.append(f"  {', '.join(section_titles)}")

            output_parts.append("\n--- Content ---\n")
            output_parts.append(content)

            return {
                "success": True,
                "output": "\n".join(output_parts),
                "metadata": metadata,
                "page_count": page_count,
                "sections": sections,
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "output": None,
            }
