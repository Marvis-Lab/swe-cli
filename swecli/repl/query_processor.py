"""Query processing for REPL."""

import json
from typing import TYPE_CHECKING, Iterable

from swecli.core.context_engineering.memory import (
    Reflector,
    Curator,
)
from swecli.repl.react_executor import ReactExecutor


if TYPE_CHECKING:
    from rich.console import Console
    from swecli.core.runtime import ModeManager
    from swecli.core.context_engineering.history import SessionManager
    from swecli.core.runtime.approval import ApprovalManager
    from swecli.core.context_engineering.history import UndoManager
    from swecli.core.context_engineering.tools.implementations import FileOperations
    from swecli.ui_textual.formatters_internal.output_formatter import OutputFormatter
    from swecli.ui_textual.components import StatusLine
    from swecli.models.config import Config
    from swecli.core.runtime import ConfigManager
    from swecli.models.message import ToolCall


class QueryProcessor:
    """Processes user queries using ReAct pattern.
    
    This class orchestrates query processing by coordinating:
    - Query enhancement (@ file references)
    - Message preparation with playbook context
    - LLM calls with progress display
    - Tool execution with approval/undo
    - ACE learning from tool execution results
    
    Note:
        THINKING_VERBS constant has been consolidated into LLMCaller.
        This class is being incrementally refactored to compose 
        specialized components (LLMCaller, QueryEnhancer, ToolExecutor).
    """

    REFLECTION_WINDOW_SIZE = 10
    MAX_PLAYBOOK_STRATEGIES = 30
    PLAYBOOK_DEBUG_PATH = "/tmp/swecli_debug/playbook_evolution.log"

    def __init__(
        self,
        console: "Console",
        session_manager: "SessionManager",
        config: "Config",
        config_manager: "ConfigManager",
        mode_manager: "ModeManager",
        file_ops: "FileOperations",
        output_formatter: "OutputFormatter",
        status_line: "StatusLine",
        message_printer_callback,
    ):
        """Initialize query processor.

        Args:
            console: Rich console for output
            session_manager: Session manager for message tracking
            config: Configuration
            config_manager: Configuration manager
            mode_manager: Mode manager for current mode
            file_ops: File operations for query enhancement
            output_formatter: Output formatter for tool results
            status_line: Status line renderer
            message_printer_callback: Callback to print markdown messages
        """
        self.console = console
        self.session_manager = session_manager
        self.config = config
        self.config_manager = config_manager
        self.mode_manager = mode_manager
        self.file_ops = file_ops
        self.output_formatter = output_formatter
        self.status_line = status_line
        self._print_markdown_message = message_printer_callback

        # UI state trackers
        self._last_latency_ms = None
        self._last_operation_summary = "—"
        self._last_error = None
        self._notification_center = None

        # Interrupt support - track current task monitor
        self._current_task_monitor: Optional[Any] = None

        # ACE Components - Initialize on first use (lazy loading)
        self._ace_reflector: Optional[Reflector] = None
        self._ace_curator: Optional[Curator] = None
        self._last_agent_response: Optional[AgentResponse] = None
        self._execution_count = 0

        # Composed components (SOLID refactoring)
        from swecli.repl.query_enhancer import QueryEnhancer
        self._query_enhancer = QueryEnhancer(
            file_ops=file_ops,
            session_manager=session_manager,
            config=config,
            console=console,
        )
        
        from swecli.repl.llm_caller import LLMCaller
        self._llm_caller = LLMCaller(console=console)
        
        from swecli.repl.tool_executor import ToolExecutor
        self._tool_executor = ToolExecutor(
            console,
            output_formatter,
            mode_manager,
            session_manager,
            self._ace_reflector,
            self._ace_curator
        )
        self._react_executor = ReactExecutor(
            console,
            session_manager,
            config,
            self._llm_caller,
            self._tool_executor
        )


    def set_notification_center(self, notification_center):
        """Set notification center for status line rendering.

        Args:
            notification_center: Notification center instance
        """
        self._notification_center = notification_center

    def request_interrupt(self) -> bool:
        """Request interrupt of currently running task (LLM call or tool execution).

        Returns:
            True if interrupt was requested, False if no task is running
        """
        if self._current_task_monitor is not None:
            self._current_task_monitor.request_interrupt()
            return True
        return False

    def _init_ace_components(self, agent):
        """Initialize ACE components lazily on first use.
        
        Safe to call multiple times - idempotent and handles errors gracefully.

        Args:
            agent: Agent with LLM client
        """
        if self._ace_reflector is None:
            try:
                # Initialize ACE roles with native implementation
                # The native components use swecli's LLM client directly
                self._ace_reflector = Reflector(agent.client)
                self._ace_curator = Curator(agent.client)
            except Exception:  # pragma: no cover
                # ACE initialization failed - leave components as None
                # record_tool_learnings will safely handle None components
                pass


    def enhance_query(self, query: str) -> tuple[str, list[dict]]:
        """Enhance query with file contents if referenced.

        Delegates to QueryEnhancer.

        Args:
            query: Original query

        Returns:
            Tuple of (enhanced_query, image_blocks):
            - enhanced_query: Query with @ stripped and file contents appended
            - image_blocks: List of multimodal image blocks for vision API
        """
        return self._query_enhancer.enhance_query(query)

    def _prepare_messages(
        self,
        query: str,
        enhanced_query: str,
        agent,
        image_blocks: list[dict] | None = None,
    ) -> list:
        """Prepare messages for LLM API call.

        Delegates to QueryEnhancer.

        Args:
            query: Original query
            enhanced_query: Query with file contents or @ references processed
            agent: Agent with system prompt
            image_blocks: Optional list of multimodal image blocks for vision API

        Returns:
            List of API messages
        """
        return self._query_enhancer.prepare_messages(
            query, enhanced_query, agent, image_blocks=image_blocks
        )

    def _call_llm_with_progress(self, agent, messages, task_monitor) -> tuple:
        """Call LLM with progress display.
        
        Delegates to LLMCaller for improved error handling and logging.

        Args:
            agent: Agent to use
            messages: Message history
            task_monitor: Task monitor for tracking

        Returns:
            Tuple of (response, latency_ms)
        """
        # Track current monitor for interrupt support
        self._current_task_monitor = task_monitor
        try:
            return self._llm_caller.call_llm_with_progress(agent, messages, task_monitor)
        finally:
            self._current_task_monitor = None

    def _record_tool_learnings(
        self,
        query: str,
        tool_call_objects: Iterable["ToolCall"],
        outcome: str,
        agent,
    ) -> None:
        """Use ACE Reflector and Curator to evolve playbook from tool execution.
        
        Delegates to ToolExecutor. ToolExecutor.record_tool_learnings has
        proper error handling, so we don't need additional try-except here.

        Args:
            query: User's query
            tool_call_objects: Tool calls that were executed
            outcome: "success", "error", or "partial"
            agent: Agent with LLM client (for ACE initialization)
        """
        # Initialize ACE components (safe - handles errors internally)
        self._init_ace_components(agent)
        
        # Set ACE components on ToolExecutor (may be None if init failed)
        self._tool_executor.set_ace_components(self._ace_reflector, self._ace_curator)
        
        # Set last agent response
        if self._last_agent_response:
            self._tool_executor.set_last_agent_response(str(self._last_agent_response))
        
        # Delegate to ToolExecutor (has internal error handling)
        self._tool_executor.record_tool_learnings(query, tool_call_objects, outcome, agent)


    def _format_tool_feedback(self, tool_calls: list, outcome: str) -> str:
        """Format tool execution results as feedback string for ACE Reflector.
        
        Delegates to ToolExecutor.

        Args:
            tool_calls: List of ToolCall objects with results
            outcome: "success", "error", or "partial"

        Returns:
            Formatted feedback string
        """
        return self._tool_executor._format_tool_feedback(tool_calls, outcome)


    def _render_status_line(self):
        """Render the status line with current context."""
        total_tokens = self.session_manager.current_session.total_tokens() if self.session_manager.current_session else 0
        self.status_line.render(
            model=self.config.model,
            working_dir=self.config_manager.working_dir,
            tokens_used=total_tokens,
            tokens_limit=self.config.max_context_tokens,
            mode=self.mode_manager.current_mode.value.upper(),
            latency_ms=self._last_latency_ms,
            key_hints=[
                ("Esc S", "Status detail"),
                ("Esc C", "Context"),
                ("Esc N", "Notifications"),
                ("/help", "Commands"),
            ],
            notifications=[note.summary() for note in self._notification_center.latest(2)] if self._notification_center and self._notification_center.has_items() else None,
        )

    def process_query(
        self,
        query: str,
        agent,
        tool_registry,
        approval_manager: "ApprovalManager",
        undo_manager: "UndoManager",
    ) -> tuple:
        """Process a user query with AI using ReAct pattern.

        Args:
            query: User query
            agent: Agent to use for LLM calls
            tool_registry: Tool registry for executing tools
            approval_manager: Approval manager for user confirmations
            undo_manager: Undo manager for operation history

        Returns:
            Tuple of (last_operation_summary, last_error, last_latency_ms)
        """
        from swecli.models.message import ChatMessage, Role

        # Add user message to session
        user_msg = ChatMessage(role=Role.USER, content=query)
        self.session_manager.add_message(user_msg, self.config.auto_save_interval)

        # Enhance query with file contents (returns enhanced text + image blocks)
        enhanced_query, image_blocks = self.enhance_query(query)

        # Prepare messages for API (handles multimodal content if images present)
        messages = self._prepare_messages(query, enhanced_query, agent, image_blocks)

        # Delegate to ReactExecutor
        return self._react_executor.execute(
            query,
            messages,
            agent,
            tool_registry,
            approval_manager,
            undo_manager
        )

    def process_query_with_callback(
        self,
        query: str,
        agent,
        tool_registry,
        approval_manager: "ApprovalManager",
        undo_manager: "UndoManager",
        ui_callback,
    ) -> tuple:
        """Process a user query with AI using ReAct pattern with UI callback for real-time updates.

        Args:
            query: User query
            agent: Agent to use for LLM calls
            tool_registry: Tool registry for executing tools
            approval_manager: Approval manager for user confirmations
            undo_manager: Undo manager for operation history
            ui_callback: UI callback for real-time tool display

        Returns:
            Tuple of (last_operation_summary, last_error, last_latency_ms)
        """
        from swecli.models.message import ChatMessage, Role

        # Add user message to session
        user_msg = ChatMessage(role=Role.USER, content=query)
        self.session_manager.add_message(user_msg, self.config.auto_save_interval)

        # Enhance query with file contents (returns enhanced text + image blocks)
        enhanced_query, image_blocks = self.enhance_query(query)

        # Prepare messages for API (handles multimodal content if images present)
        messages = self._prepare_messages(query, enhanced_query, agent, image_blocks)

        # Delegate to ReactExecutor with ui_callback
        return self._react_executor.execute(
            query,
            messages,
            agent,
            tool_registry,
            approval_manager,
            undo_manager,
            ui_callback=ui_callback
        )
