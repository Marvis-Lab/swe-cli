"""Agent executor for WebSocket queries with streaming support."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Tuple

from swecli.web.state import WebState
from swecli.web.logging_config import logger
from swecli.models.message import ChatMessage, Role
from swecli.models.agent_deps import AgentDependencies
from swecli.core.runtime import ConfigManager
from swecli.models.config import AppConfig


class AgentExecutor:
    """Executes agent queries in background with WebSocket streaming."""

    def __init__(self, state: WebState):
        """Initialize agent executor.

        Args:
            state: Shared web state
        """
        self.state = state
        self.executor = ThreadPoolExecutor(max_workers=4)

    async def execute_query(
        self,
        message: str,
        ws_manager: Any,
    ) -> None:
        """Execute query and stream results via WebSocket.

        Args:
            message: User query
            ws_manager: WebSocket manager for broadcasting
        """
        try:
            # Broadcast message start
            try:
                await ws_manager.broadcast({
                    "type": "message_start",
                    "data": {"messageId": str(time.time())}
                })
            except Exception as e:
                logger.error(f"Failed to broadcast message_start: {e}")

            # Run agent in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                self._run_agent_sync,
                message,
                ws_manager,
                loop,  # Pass the event loop
            )

            # Add assistant response to session
            logger.info(f"Agent response: success={response.get('success')}, has_content={bool(response.get('content'))}")
            if response and response.get("success"):
                assistant_content = response.get("content", "")
                raw_assistant_content = assistant_content
                history = response.get("messages") or []
                for msg in reversed(history):
                    if msg.get("role") == "assistant":
                        raw_assistant_content = msg.get("content", raw_assistant_content)
                        break

                metadata = {}
                if raw_assistant_content is not None:
                    metadata["raw_content"] = raw_assistant_content

                assistant_msg = ChatMessage(
                    role=Role.ASSISTANT,
                    content=assistant_content,
                    metadata=metadata,
                )
                self.state.add_message(assistant_msg)

            # Save session to persist messages immediately
            self.state.session_manager.save_session()

            # Broadcast message complete
            try:
                await ws_manager.broadcast({
                    "type": "message_complete",
                    "data": {"messageId": str(time.time())}
                })
            except Exception as e:
                logger.error(f"Failed to broadcast message_complete: {e}")

        except Exception as e:
            # Broadcast error
            logger.error(f"❌ Agent execution error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                await ws_manager.broadcast({
                    "type": "error",
                    "data": {"message": str(e)}
                })
            except Exception as broadcast_err:
                logger.error(f"Failed to broadcast error: {broadcast_err}")

    def _run_agent_sync(self, message: str, ws_manager: Any, loop: asyncio.AbstractEventLoop) -> Dict[str, Any]:
        """Run agent synchronously in thread pool.

        Args:
            message: User query
            ws_manager: WebSocket manager
            loop: Event loop for async operations

        Returns:
            Agent response
        """
        from swecli.core.runtime.services import RuntimeService
        from swecli.core.context_engineering.tools.implementations import (
            FileOperations,
            WriteTool,
            EditTool,
            BashTool,
            WebFetchTool,
            OpenBrowserTool,
            WebScreenshotTool,
        )
        from swecli.core.context_engineering.tools.implementations.web_search_tool import WebSearchTool
        from swecli.core.context_engineering.tools.implementations.notebook_edit_tool import NotebookEditTool
        from swecli.core.context_engineering.tools.implementations.ask_user_tool import AskUserTool
        from swecli.web.web_approval_manager import WebApprovalManager
        from swecli.web.ws_tool_broadcaster import WebSocketToolBroadcaster

        # Clear any previous interrupt flags
        self.state.clear_interrupt()

        # Resolve config/working directory for current session
        config_manager, config, working_dir = self._resolve_runtime_context()

        # Initialize tools
        file_ops = FileOperations(config, working_dir)
        write_tool = WriteTool(config, working_dir)
        edit_tool = EditTool(config, working_dir)
        bash_tool = BashTool(config, working_dir)
        web_fetch_tool = WebFetchTool(config, working_dir)
        web_search_tool = WebSearchTool(config, working_dir)
        notebook_edit_tool = NotebookEditTool(working_dir)
        ask_user_tool = AskUserTool()  # Uses console fallback in web mode
        open_browser_tool = OpenBrowserTool(config, working_dir)
        web_screenshot_tool = WebScreenshotTool(config, working_dir)

        # Create web-based approval manager
        web_approval_manager = WebApprovalManager(ws_manager, loop)

        # Build runtime suite
        runtime_service = RuntimeService(config_manager, self.state.mode_manager)
        runtime_suite = runtime_service.build_suite(
            file_ops=file_ops,
            write_tool=write_tool,
            edit_tool=edit_tool,
            bash_tool=bash_tool,
            web_fetch_tool=web_fetch_tool,
            web_search_tool=web_search_tool,
            notebook_edit_tool=notebook_edit_tool,
            ask_user_tool=ask_user_tool,
            open_browser_tool=open_browser_tool,
            web_screenshot_tool=web_screenshot_tool,
            mcp_manager=self.state.mcp_manager,
        )

        # Wrap tool registry with WebSocket broadcaster
        wrapped_registry = WebSocketToolBroadcaster(
            runtime_suite.tool_registry,
            ws_manager,
            loop,
            working_dir=working_dir,
        )

        # Get agent and replace its tool registry with wrapped version
        agent = runtime_suite.agents.normal
        agent.tool_registry = wrapped_registry
        # Pass the state to the agent for interrupt checking
        agent.web_state = self.state

        # Get session messages
        session = self.state.session_manager.get_current_session()
        if not session:
            session = self.state.session_manager.create_session(
                working_directory=str(working_dir)
            )

        message_history = session.to_api_messages()

        # Create agent dependencies with web approval manager
        deps = AgentDependencies(
            mode_manager=self.state.mode_manager,
            approval_manager=web_approval_manager,  # Use web-based approval
            undo_manager=self.state.undo_manager,
            session_manager=self.state.session_manager,
            working_dir=working_dir,
            console=None,  # No console for web
            config=config,
        )

        # Run agent
        try:
            result = agent.run_sync(
                message,
                deps,
                message_history=message_history,
            )

            # Broadcast the full response as a chunk
            # (Streaming at character level will be added later)
            logger.info(f"Agent run_sync completed: success={result.get('success')}")
            if result.get("success"):
                content = result.get("content", "")
                logger.info(f"Broadcasting message_chunk with content length: {len(str(content))}")
                try:
                    # Schedule the broadcast coroutine in the event loop
                    future = asyncio.run_coroutine_threadsafe(
                        ws_manager.broadcast({
                            "type": "message_chunk",
                            "data": {"content": str(content)}
                        }),
                        loop
                    )
                    # Wait for it to complete
                    future.result(timeout=5)
                    logger.info("message_chunk broadcasted successfully")
                except Exception as e:
                    logger.error(f"Failed to broadcast message_chunk: {e}")
            else:
                logger.warning(f"Agent returned success=False, not broadcasting message_chunk")

            return result

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "content": f"Error: {str(e)}"
            }

    def _resolve_runtime_context(self) -> Tuple[ConfigManager, AppConfig, Path]:
        """Determine config manager, config, and working dir for current session."""
        session = self.state.session_manager.get_current_session()
        if session and session.working_directory:
            working_dir = Path(session.working_directory).expanduser().resolve()
            config_manager = ConfigManager(working_dir)
            config = config_manager.get_config()
        else:
            config_manager = self.state.config_manager
            config = config_manager.get_config()
            working_dir = Path(config_manager.working_dir).resolve()

        try:
            config_manager.ensure_directories()
        except Exception:
            pass

        return config_manager, config, working_dir
