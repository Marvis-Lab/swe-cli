"""Tests for Thinking Mode feature.

Tests the think tool and related components for capturing and displaying
model reasoning content.
"""

from unittest.mock import MagicMock

from swecli.core.context_engineering.tools.handlers.thinking_handler import (
    ThinkingHandler,
    ThinkingBlock,
)


class TestThinkingHandler:
    """Tests for ThinkingHandler state management."""

    def test_init_creates_empty_state(self):
        """Test handler initializes with empty state."""
        handler = ThinkingHandler()
        assert handler.block_count == 0
        assert handler.is_visible is True
        assert handler.get_all_thinking() == []

    def test_add_thinking_returns_success(self):
        """Test adding thinking content."""
        handler = ThinkingHandler()
        result = handler.add_thinking("Step 1: analyze...")

        assert result["success"] is True
        assert result["_thinking_content"] == "Step 1: analyze..."
        assert result["thinking_id"] == "think-1"
        assert result["output"] == "Step 1: analyze..."  # Included in message history for next LLM call

    def test_add_thinking_strips_whitespace(self):
        """Test that thinking content is stripped."""
        handler = ThinkingHandler()
        result = handler.add_thinking("  content with spaces  \n")

        assert result["_thinking_content"] == "content with spaces"

    def test_add_thinking_empty_fails(self):
        """Test that empty content fails."""
        handler = ThinkingHandler()

        result = handler.add_thinking("")
        assert result["success"] is False
        assert "empty" in result["error"].lower()

        result = handler.add_thinking("   ")
        assert result["success"] is False

        result = handler.add_thinking(None)
        assert result["success"] is False

    def test_add_thinking_increments_id(self):
        """Test that thinking IDs increment."""
        handler = ThinkingHandler()

        r1 = handler.add_thinking("First")
        r2 = handler.add_thinking("Second")
        r3 = handler.add_thinking("Third")

        assert r1["thinking_id"] == "think-1"
        assert r2["thinking_id"] == "think-2"
        assert r3["thinking_id"] == "think-3"

    def test_get_all_thinking_returns_blocks(self):
        """Test getting all thinking blocks."""
        handler = ThinkingHandler()
        handler.add_thinking("First thought")
        handler.add_thinking("Second thought")

        blocks = handler.get_all_thinking()

        assert len(blocks) == 2
        assert isinstance(blocks[0], ThinkingBlock)
        assert blocks[0].content == "First thought"
        assert blocks[1].content == "Second thought"

    def test_get_latest_thinking(self):
        """Test getting the most recent thinking block."""
        handler = ThinkingHandler()

        assert handler.get_latest_thinking() is None

        handler.add_thinking("First")
        handler.add_thinking("Second")

        latest = handler.get_latest_thinking()
        assert latest is not None
        assert latest.content == "Second"

    def test_clear_resets_blocks(self):
        """Test clearing thinking blocks."""
        handler = ThinkingHandler()
        handler.add_thinking("content")
        handler.add_thinking("more content")

        handler.clear()

        assert handler.block_count == 0
        assert handler.get_all_thinking() == []

    def test_clear_resets_id_counter(self):
        """Test that clear resets ID counter."""
        handler = ThinkingHandler()
        handler.add_thinking("First")
        handler.add_thinking("Second")
        handler.clear()

        result = handler.add_thinking("After clear")
        assert result["thinking_id"] == "think-1"  # ID reset to 1

    def test_toggle_visibility(self):
        """Test visibility toggle."""
        handler = ThinkingHandler()
        assert handler.is_visible is True

        new_state = handler.toggle_visibility()
        assert new_state is False
        assert handler.is_visible is False

        new_state = handler.toggle_visibility()
        assert new_state is True
        assert handler.is_visible is True

    def test_block_count_property(self):
        """Test block_count property."""
        handler = ThinkingHandler()
        assert handler.block_count == 0

        handler.add_thinking("One")
        assert handler.block_count == 1

        handler.add_thinking("Two")
        assert handler.block_count == 2

        handler.clear()
        assert handler.block_count == 0


class TestThinkToolSchema:
    """Tests for think tool schema in tool_schema_builder."""

    def test_think_schema_exists(self):
        """Test that think tool schema is defined."""
        from swecli.core.agents.components.tool_schema_builder import _BUILTIN_TOOL_SCHEMAS

        names = [s["function"]["name"] for s in _BUILTIN_TOOL_SCHEMAS]
        assert "think" in names

    def test_think_schema_structure(self):
        """Test think tool schema has correct structure."""
        from swecli.core.agents.components.tool_schema_builder import _BUILTIN_TOOL_SCHEMAS

        think_schema = next(
            s for s in _BUILTIN_TOOL_SCHEMAS if s["function"]["name"] == "think"
        )

        assert think_schema["type"] == "function"
        func = think_schema["function"]
        assert "description" in func
        assert "reasoning" in func["description"].lower() or "thought" in func["description"].lower()

        params = func["parameters"]
        assert params["type"] == "object"
        assert "content" in params["properties"]
        assert "content" in params["required"]

    def test_think_in_planning_tools(self):
        """Test that think is allowed in plan mode."""
        from swecli.core.agents.components.tool_schema_builder import PLANNING_TOOLS

        assert "think" in PLANNING_TOOLS


class TestThinkToolExecution:
    """Tests for think tool execution in ToolRegistry."""

    def test_registry_has_thinking_handler(self):
        """Test that ToolRegistry initializes thinking_handler."""
        from swecli.core.context_engineering.tools.registry import ToolRegistry

        registry = ToolRegistry()
        assert hasattr(registry, "thinking_handler")
        assert isinstance(registry.thinking_handler, ThinkingHandler)

    def test_execute_think_success(self):
        """Test executing think tool successfully."""
        from swecli.core.context_engineering.tools.registry import ToolRegistry

        registry = ToolRegistry()
        result = registry.execute_tool("think", {"content": "Analyzing the problem..."})

        assert result["success"] is True
        assert result["_thinking_content"] == "Analyzing the problem..."
        assert result["output"] == "Analyzing the problem..."  # Included in message history

    def test_execute_think_empty_content_fails(self):
        """Test executing think tool with empty content."""
        from swecli.core.context_engineering.tools.registry import ToolRegistry

        registry = ToolRegistry()
        result = registry.execute_tool("think", {"content": ""})

        assert result["success"] is False
        assert "empty" in result["error"].lower()

    def test_execute_think_allowed_in_plan_mode(self):
        """Test that think is allowed in plan mode."""
        from swecli.core.context_engineering.tools.registry import _PLAN_READ_ONLY_TOOLS

        assert "think" in _PLAN_READ_ONLY_TOOLS


class TestThinkingUICallback:
    """Tests for thinking UI callback integration."""

    def test_callback_has_thinking_visible_attribute(self):
        """Test that TextualUICallback initializes thinking visibility."""
        from swecli.ui_textual.ui_callback import TextualUICallback

        mock_conversation = MagicMock()
        callback = TextualUICallback(mock_conversation)

        assert hasattr(callback, "_thinking_visible")
        assert callback._thinking_visible is True

    def test_on_thinking_calls_add_thinking_block(self):
        """Test that on_thinking calls conversation.add_thinking_block."""
        from swecli.ui_textual.ui_callback import TextualUICallback

        mock_conversation = MagicMock()
        mock_conversation.add_thinking_block = MagicMock()
        callback = TextualUICallback(mock_conversation)

        # Mock _run_on_ui to call function directly
        callback._run_on_ui = lambda f, *args: f(*args)

        callback.on_thinking("Test thinking content")

        mock_conversation.add_thinking_block.assert_called_once_with("Test thinking content")

    def test_on_thinking_skipped_when_not_visible(self):
        """Test that on_thinking is skipped when visibility is off."""
        from swecli.ui_textual.ui_callback import TextualUICallback

        mock_conversation = MagicMock()
        mock_conversation.add_thinking_block = MagicMock()
        callback = TextualUICallback(mock_conversation)
        callback._thinking_visible = False

        callback.on_thinking("Test content")

        mock_conversation.add_thinking_block.assert_not_called()

    def test_on_thinking_reads_from_chat_app_state(self):
        """Test that on_thinking reads visibility from chat_app._thinking_visible."""
        from swecli.ui_textual.ui_callback import TextualUICallback

        mock_conversation = MagicMock()
        mock_conversation.add_thinking_block = MagicMock()
        mock_app = MagicMock()
        mock_app._thinking_visible = False  # App says hidden

        callback = TextualUICallback(mock_conversation, chat_app=mock_app)
        callback._thinking_visible = True  # Local state says visible
        callback._run_on_ui = lambda f, *args: f(*args)

        callback.on_thinking("Test content")

        # Should NOT display because app state says hidden
        mock_conversation.add_thinking_block.assert_not_called()

    def test_on_thinking_uses_app_state_when_visible(self):
        """Test that on_thinking displays when chat_app._thinking_visible is True."""
        from swecli.ui_textual.ui_callback import TextualUICallback

        mock_conversation = MagicMock()
        mock_conversation.add_thinking_block = MagicMock()
        mock_app = MagicMock()
        mock_app._thinking_visible = True  # App says visible

        callback = TextualUICallback(mock_conversation, chat_app=mock_app)
        callback._run_on_ui = lambda f, *args: f(*args)

        callback.on_thinking("Test content")

        # Should display because app state says visible
        mock_conversation.add_thinking_block.assert_called_once_with("Test content")

    def test_on_thinking_skipped_for_empty_content(self):
        """Test that on_thinking is skipped for empty content."""
        from swecli.ui_textual.ui_callback import TextualUICallback

        mock_conversation = MagicMock()
        mock_conversation.add_thinking_block = MagicMock()
        callback = TextualUICallback(mock_conversation)

        callback.on_thinking("")
        callback.on_thinking("   ")

        mock_conversation.add_thinking_block.assert_not_called()

    def test_toggle_thinking_visibility(self):
        """Test toggle_thinking_visibility method (fallback when no app)."""
        from swecli.ui_textual.ui_callback import TextualUICallback

        mock_conversation = MagicMock()
        callback = TextualUICallback(mock_conversation)

        assert callback._thinking_visible is True

        new_state = callback.toggle_thinking_visibility()
        assert new_state is False
        assert callback._thinking_visible is False

        new_state = callback.toggle_thinking_visibility()
        assert new_state is True
        assert callback._thinking_visible is True

    def test_toggle_thinking_visibility_syncs_with_app(self):
        """Test toggle_thinking_visibility syncs with chat_app._thinking_visible."""
        from swecli.ui_textual.ui_callback import TextualUICallback

        mock_conversation = MagicMock()
        mock_app = MagicMock()
        mock_app._thinking_visible = True

        callback = TextualUICallback(mock_conversation, chat_app=mock_app)

        # Toggle should change both app and local state
        new_state = callback.toggle_thinking_visibility()
        assert new_state is False
        assert mock_app._thinking_visible is False
        assert callback._thinking_visible is False

        # Toggle again
        new_state = callback.toggle_thinking_visibility()
        assert new_state is True
        assert mock_app._thinking_visible is True
        assert callback._thinking_visible is True

    def test_on_tool_result_handles_think_tool(self):
        """Test that on_tool_result calls on_thinking for think tool."""
        from swecli.ui_textual.ui_callback import TextualUICallback

        mock_conversation = MagicMock()
        mock_conversation.add_thinking_block = MagicMock()
        callback = TextualUICallback(mock_conversation)

        # Mock _run_on_ui to call function directly
        callback._run_on_ui = lambda f, *args: f(*args)

        result = {
            "success": True,
            "_thinking_content": "My reasoning here",
            "output": "",
        }

        callback.on_tool_result("think", {"content": "My reasoning here"}, result)

        mock_conversation.add_thinking_block.assert_called_once_with("My reasoning here")


class TestCallbackProtocol:
    """Tests for callback protocol compliance."""

    def test_base_ui_callback_has_on_thinking(self):
        """Test BaseUICallback has on_thinking method."""
        from swecli.ui_textual.callback_interface import BaseUICallback

        callback = BaseUICallback()
        assert hasattr(callback, "on_thinking")
        # Should not raise
        callback.on_thinking("test content")

    def test_forwarding_callback_forwards_on_thinking(self):
        """Test ForwardingUICallback forwards on_thinking."""
        from swecli.ui_textual.callback_interface import ForwardingUICallback

        mock_parent = MagicMock()
        mock_parent.on_thinking = MagicMock()

        callback = ForwardingUICallback(mock_parent)
        callback.on_thinking("test content")

        mock_parent.on_thinking.assert_called_once_with("test content")


class TestStyleTokens:
    """Tests for thinking-related style tokens."""

    def test_thinking_tokens_exist(self):
        """Test that THINKING and THINKING_ICON tokens are defined."""
        from swecli.ui_textual.style_tokens import THINKING, THINKING_ICON

        assert THINKING is not None
        assert isinstance(THINKING, str)
        assert THINKING.startswith("#")  # Should be a hex color

        assert THINKING_ICON is not None
        assert isinstance(THINKING_ICON, str)


class TestMessageRenderer:
    """Tests for thinking block rendering."""

    def test_add_thinking_block_method_exists(self):
        """Test DefaultMessageRenderer has add_thinking_block."""
        from swecli.ui_textual.widgets.conversation.message_renderer import DefaultMessageRenderer

        mock_log = MagicMock()
        renderer = DefaultMessageRenderer(mock_log)

        assert hasattr(renderer, "add_thinking_block")

    def test_add_thinking_block_writes_to_log(self):
        """Test add_thinking_block writes to log."""
        from swecli.ui_textual.widgets.conversation.message_renderer import DefaultMessageRenderer

        mock_log = MagicMock()
        renderer = DefaultMessageRenderer(mock_log)

        renderer.add_thinking_block("My thinking content")

        # Should write the thinking text and a blank line
        assert mock_log.write.call_count == 2

    def test_add_thinking_block_skips_empty(self):
        """Test add_thinking_block skips empty content."""
        from swecli.ui_textual.widgets.conversation.message_renderer import DefaultMessageRenderer

        mock_log = MagicMock()
        renderer = DefaultMessageRenderer(mock_log)

        renderer.add_thinking_block("")
        renderer.add_thinking_block("   ")

        mock_log.write.assert_not_called()


class TestConversationLog:
    """Tests for ConversationLog delegation."""

    def test_add_thinking_block_delegates(self):
        """Test ConversationLog.add_thinking_block delegates to renderer."""
        from swecli.ui_textual.widgets.conversation_log import ConversationLog

        # ConversationLog inherits from RichLog which requires more setup
        # Use a simpler approach - just verify the method exists
        assert hasattr(ConversationLog, "add_thinking_block")


class TestStatusBar:
    """Tests for StatusBar thinking mode display."""

    def test_status_bar_has_thinking_enabled_attribute(self):
        """Test StatusBar initializes with thinking_enabled."""
        from swecli.ui_textual.widgets.status_bar import StatusBar

        status_bar = StatusBar()
        assert hasattr(status_bar, "thinking_enabled")
        assert status_bar.thinking_enabled is True

    def test_set_thinking_enabled(self):
        """Test set_thinking_enabled method."""
        from swecli.ui_textual.widgets.status_bar import StatusBar

        status_bar = StatusBar()
        # Mock update_status to avoid Textual context requirement
        status_bar.update_status = MagicMock()

        status_bar.set_thinking_enabled(False)
        assert status_bar.thinking_enabled is False
        status_bar.update_status.assert_called()

        status_bar.set_thinking_enabled(True)
        assert status_bar.thinking_enabled is True


class TestThinkingModeInjection:
    """Tests for dynamic thinking instruction placeholder replacement."""

    def test_placeholder_replaced_when_thinking_on(self):
        """Test that {thinking_instruction} is replaced with 'use think tool' when ON."""
        from swecli.repl.query_enhancer import QueryEnhancer

        file_ops = MagicMock()
        session_manager = MagicMock()
        session_manager.current_session = None
        config = MagicMock()
        config.playbook = None
        console = MagicMock()

        enhancer = QueryEnhancer(file_ops, session_manager, config, console)
        mock_agent = MagicMock()
        mock_agent.system_prompt = "1. **Think**: {thinking_instruction}"

        messages = enhancer.prepare_messages(
            query="Help me",
            enhanced_query="Help me",
            agent=mock_agent,
            thinking_visible=True
        )

        system_content = messages[0]["content"]
        assert "{thinking_instruction}" not in system_content
        assert "thinking mode is on" in system_content.lower()
        assert "must call the `think` tool first" in system_content.lower()

    def test_placeholder_replaced_when_thinking_off(self):
        """Test that {thinking_instruction} is replaced with 'explain briefly' when OFF."""
        from swecli.repl.query_enhancer import QueryEnhancer

        file_ops = MagicMock()
        session_manager = MagicMock()
        session_manager.current_session = None
        config = MagicMock()
        config.playbook = None
        console = MagicMock()

        enhancer = QueryEnhancer(file_ops, session_manager, config, console)
        mock_agent = MagicMock()
        mock_agent.system_prompt = "1. **Think**: {thinking_instruction}"

        messages = enhancer.prepare_messages(
            query="Help me",
            enhanced_query="Help me",
            agent=mock_agent,
            thinking_visible=False
        )

        system_content = messages[0]["content"]
        assert "{thinking_instruction}" not in system_content
        assert "briefly explain" in system_content.lower()

    def test_no_placeholder_leaves_content_unchanged(self):
        """Test that prompts without placeholder are left unchanged."""
        from swecli.repl.query_enhancer import QueryEnhancer

        file_ops = MagicMock()
        session_manager = MagicMock()
        session_manager.current_session = None
        config = MagicMock()
        config.playbook = None
        console = MagicMock()

        enhancer = QueryEnhancer(file_ops, session_manager, config, console)
        mock_agent = MagicMock()
        mock_agent.system_prompt = "No placeholder here"

        messages = enhancer.prepare_messages(
            query="Help me",
            enhanced_query="Help me",
            agent=mock_agent,
            thinking_visible=True
        )

        system_content = messages[0]["content"]
        assert system_content == "No placeholder here"


class TestThinkingModeSchemaFiltering:
    """Tests for think tool schema filtering based on thinking mode visibility."""

    def test_think_tool_included_when_visible(self):
        """Test that think tool is in schemas when thinking_visible=True."""
        from swecli.core.agents.components.tool_schema_builder import ToolSchemaBuilder

        mock_registry = MagicMock()
        mock_registry.subagent_manager = None
        mock_registry.get_all_mcp_tools.return_value = []

        builder = ToolSchemaBuilder(mock_registry)
        schemas = builder.build(thinking_visible=True)

        tool_names = [s.get("function", {}).get("name") for s in schemas]
        assert "think" in tool_names

    def test_think_tool_excluded_when_not_visible(self):
        """Test that think tool is NOT in schemas when thinking_visible=False."""
        from swecli.core.agents.components.tool_schema_builder import ToolSchemaBuilder

        mock_registry = MagicMock()
        mock_registry.subagent_manager = None
        mock_registry.get_all_mcp_tools.return_value = []

        builder = ToolSchemaBuilder(mock_registry)
        schemas = builder.build(thinking_visible=False)

        tool_names = [s.get("function", {}).get("name") for s in schemas]
        assert "think" not in tool_names

    def test_other_tools_preserved_when_think_filtered(self):
        """Test that other tools are preserved when think tool is filtered out."""
        from swecli.core.agents.components.tool_schema_builder import ToolSchemaBuilder

        mock_registry = MagicMock()
        mock_registry.subagent_manager = None
        mock_registry.get_all_mcp_tools.return_value = []

        builder = ToolSchemaBuilder(mock_registry)
        schemas_with_think = builder.build(thinking_visible=True)
        schemas_without_think = builder.build(thinking_visible=False)

        # Should have exactly one less tool (think)
        assert len(schemas_without_think) == len(schemas_with_think) - 1

        # All other tools should still be present
        names_with = {s.get("function", {}).get("name") for s in schemas_with_think}
        names_without = {s.get("function", {}).get("name") for s in schemas_without_think}

        assert names_with - names_without == {"think"}
