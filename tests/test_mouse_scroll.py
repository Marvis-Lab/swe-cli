"""Tests for mouse scroll and text selection functionality.

These tests verify that mouse scroll and text selection are properly enabled
after the migration from mistral-vibe's TUI approach.
"""

import inspect
from unittest.mock import Mock, MagicMock, patch


class TestMouseEnabled:
    """Tests verifying mouse is properly enabled in the TUI."""

    def test_chat_app_mouse_enabled(self):
        """Verify ENABLE_MOUSE is not set to False in chat_app."""
        from swecli.ui_textual.chat_app import SWECLIChatApp

        # ENABLE_MOUSE should either be True or not set (defaults to True)
        enable_mouse = getattr(SWECLIChatApp, 'ENABLE_MOUSE', True)
        assert enable_mouse is True or enable_mouse is None, \
            f"ENABLE_MOUSE should be True or not set, got {enable_mouse}"

    def test_runner_enables_mouse(self):
        """Verify runner passes mouse=True to app.run_async."""
        from swecli.ui_textual import runner
        source = inspect.getsource(runner)

        # Check that mouse=True is in the source (or mouse=False is NOT)
        assert "mouse=True" in source, \
            "runner.py should have mouse=True in app.run_async call"

    def test_no_mouse_reset_function(self):
        """Verify _reset_terminal_mouse_mode function is removed."""
        from swecli.ui_textual import runner

        assert not hasattr(runner, '_reset_terminal_mouse_mode'), \
            "_reset_terminal_mouse_mode should be removed from runner.py"


class TestScrollController:
    """Tests for scroll controller mouse event handling."""

    def test_scroll_down_handles_event(self):
        """Test scroll controller handles mouse scroll down events."""
        from swecli.ui_textual.widgets.conversation.scroll_controller import DefaultScrollController

        mock_log = Mock()
        mock_log.scroll_relative = Mock()
        controller = DefaultScrollController(mock_log, None)

        # Simulate mouse scroll down event
        mock_event = Mock()
        mock_event.meta = False
        mock_event.stop = Mock()
        controller.on_mouse_scroll_down(mock_event)

        # Verify scroll was triggered
        mock_log.scroll_relative.assert_called_with(y=3)
        mock_event.stop.assert_called_once()

    def test_scroll_up_handles_event(self):
        """Test scroll controller handles mouse scroll up events."""
        from swecli.ui_textual.widgets.conversation.scroll_controller import DefaultScrollController

        mock_log = Mock()
        mock_log.scroll_relative = Mock()
        controller = DefaultScrollController(mock_log, None)

        # Simulate mouse scroll up event
        mock_event = Mock()
        mock_event.meta = False
        mock_event.stop = Mock()
        controller.on_mouse_scroll_up(mock_event)

        # Verify scroll was triggered (negative y for up)
        mock_log.scroll_relative.assert_called_with(y=-3)
        mock_event.stop.assert_called_once()

    def test_scroll_updates_auto_scroll_state(self):
        """Test that scrolling disables auto-scroll."""
        from swecli.ui_textual.widgets.conversation.scroll_controller import DefaultScrollController

        mock_log = Mock()
        mock_log.scroll_relative = Mock()
        mock_log.auto_scroll = True
        controller = DefaultScrollController(mock_log, None)

        assert controller.auto_scroll is True

        # Simulate scroll event
        mock_event = Mock()
        mock_event.stop = Mock()
        controller.on_mouse_scroll_down(mock_event)

        # Auto-scroll should be disabled
        assert controller.auto_scroll is False
        assert controller._user_scrolled is True


class TestClipboard:
    """Tests for clipboard utility functions."""

    def test_clipboard_module_exists(self):
        """Verify clipboard module exists and has required functions."""
        from swecli.ui_textual.utils import clipboard

        assert hasattr(clipboard, 'copy_selection_to_clipboard'), \
            "clipboard module should have copy_selection_to_clipboard function"
        assert hasattr(clipboard, '_copy_osc52'), \
            "clipboard module should have _copy_osc52 function for SSH/tmux"

    def test_copy_selection_with_no_selection(self):
        """Test copy_selection_to_clipboard handles no selection gracefully."""
        from swecli.ui_textual.utils.clipboard import copy_selection_to_clipboard

        mock_app = Mock()
        mock_app.query.return_value = []
        mock_app.notify = Mock()

        # Should not raise an error
        copy_selection_to_clipboard(mock_app)

        # Should not notify if nothing selected
        mock_app.notify.assert_not_called()

    def test_copy_selection_with_text(self):
        """Test copy_selection_to_clipboard copies selected text."""
        from swecli.ui_textual.utils.clipboard import copy_selection_to_clipboard

        # Create mock widget with selection
        mock_widget = Mock()
        mock_widget.text_selection = "some_selection"
        mock_widget.get_selection.return_value = ("selected text", None)

        mock_app = Mock()
        mock_app.query.return_value = [mock_widget]
        mock_app.notify = Mock()
        mock_app.copy_to_clipboard = Mock()

        # Mock the copy functions to succeed
        with patch('swecli.ui_textual.utils.clipboard._copy_osc52'):
            copy_selection_to_clipboard(mock_app)

        # Should notify on successful copy
        mock_app.notify.assert_called_once()
        call_args = mock_app.notify.call_args
        assert "copied to clipboard" in call_args[0][0]


class TestKeyboardScrollBindings:
    """Tests for keyboard scroll bindings (Shift+Up/Down)."""

    def test_shift_up_binding_exists(self):
        """Verify Shift+Up binding is defined."""
        from swecli.ui_textual.chat_app import SWECLIChatApp

        binding_keys = [b.key for b in SWECLIChatApp.BINDINGS]
        assert "shift+up" in binding_keys, \
            "Shift+Up binding should be defined for scroll_chat_up"

    def test_shift_down_binding_exists(self):
        """Verify Shift+Down binding is defined."""
        from swecli.ui_textual.chat_app import SWECLIChatApp

        binding_keys = [b.key for b in SWECLIChatApp.BINDINGS]
        assert "shift+down" in binding_keys, \
            "Shift+Down binding should be defined for scroll_chat_down"

    def test_chat_app_has_scroll_actions(self):
        """Verify chat app has scroll action methods."""
        from swecli.ui_textual.chat_app import SWECLIChatApp

        assert hasattr(SWECLIChatApp, 'action_scroll_chat_up'), \
            "SWECLIChatApp should have action_scroll_chat_up method"
        assert hasattr(SWECLIChatApp, 'action_scroll_chat_down'), \
            "SWECLIChatApp should have action_scroll_chat_down method"

    def test_chat_app_has_mouse_handler(self):
        """Verify chat app has on_mouse_up handler."""
        from swecli.ui_textual.chat_app import SWECLIChatApp

        assert hasattr(SWECLIChatApp, 'on_mouse_up'), \
            "SWECLIChatApp should have on_mouse_up handler for clipboard"


class TestConversationLogTextSelection:
    """Tests for text selection in ConversationLog widget."""

    def test_allow_select_returns_true(self):
        """Verify ConversationLog.allow_select returns True.

        This is critical because RichLog inherits from ScrollableContainer
        which has is_container=True. Without our override, selection would
        be blocked by Textual's `allow_select = ALLOW_SELECT and not is_container`.
        """
        from swecli.ui_textual.widgets.conversation_log import ConversationLog

        log = ConversationLog()
        assert log.allow_select is True, \
            "allow_select should return True to enable text selection"

    def test_allow_select_respects_allow_select_flag(self):
        """Verify allow_select respects the ALLOW_SELECT class variable."""
        from swecli.ui_textual.widgets.conversation_log import ConversationLog

        log = ConversationLog()

        # Default should be True
        assert log.ALLOW_SELECT is True
        assert log.allow_select is True

        # If we change ALLOW_SELECT, allow_select should reflect it
        log.ALLOW_SELECT = False
        assert log.allow_select is False

    def test_get_selection_method_exists(self):
        """Verify ConversationLog has get_selection method."""
        from swecli.ui_textual.widgets.conversation_log import ConversationLog

        log = ConversationLog()
        assert hasattr(log, 'get_selection'), \
            "ConversationLog should have get_selection method for text extraction"

    def test_get_selection_returns_none_for_empty_log(self):
        """Verify get_selection returns None when log is empty."""
        from swecli.ui_textual.widgets.conversation_log import ConversationLog
        from textual.selection import Selection

        log = ConversationLog()
        # Ensure lines is empty
        log.lines.clear() if hasattr(log.lines, 'clear') else None

        # Create a mock selection
        mock_selection = Mock(spec=Selection)

        result = log.get_selection(mock_selection)
        assert result is None, \
            "get_selection should return None for empty log"

    def test_get_selection_extracts_text_from_lines(self):
        """Verify get_selection converts Strip objects to text and extracts selection."""
        from swecli.ui_textual.widgets.conversation_log import ConversationLog

        log = ConversationLog()

        # Add some mock lines (Strip objects convert to string)
        mock_line1 = Mock()
        mock_line1.__str__ = Mock(return_value="Hello world")
        mock_line2 = Mock()
        mock_line2.__str__ = Mock(return_value="This is a test")

        log.lines.append(mock_line1)
        log.lines.append(mock_line2)

        # Create a mock selection that extracts a portion
        mock_selection = Mock()
        mock_selection.extract = Mock(return_value="world\nThis")

        result = log.get_selection(mock_selection)

        assert result is not None, "get_selection should return a result"
        assert result == ("world\nThis", "\n"), \
            "get_selection should return (extracted_text, line_ending)"

        # Verify extract was called with the combined text
        mock_selection.extract.assert_called_once()
        call_args = mock_selection.extract.call_args[0][0]
        assert "Hello world" in call_args
        assert "This is a test" in call_args

    def test_conversation_log_has_selection_import(self):
        """Verify Selection is imported in conversation_log module."""
        from swecli.ui_textual.widgets import conversation_log

        assert hasattr(conversation_log, 'Selection'), \
            "conversation_log module should import Selection from textual.selection"


class TestTextSelectionIntegration:
    """Integration tests for text selection with clipboard."""

    def test_clipboard_can_get_selection_from_conversation_log(self):
        """Verify clipboard utility can extract selection from ConversationLog."""
        from swecli.ui_textual.utils.clipboard import copy_selection_to_clipboard
        from swecli.ui_textual.widgets.conversation_log import ConversationLog

        # Create a ConversationLog with content
        log = ConversationLog()

        # Add mock lines
        mock_line = Mock()
        mock_line.__str__ = Mock(return_value="Test content for selection")
        log.lines.append(mock_line)

        # Set up a mock selection on the log
        mock_selection = Mock()
        mock_selection.extract = Mock(return_value="Test content")
        log._text_selection = mock_selection  # Simulate active selection

        # Create mock app that returns our log
        mock_app = Mock()
        mock_app.query.return_value = [log]
        mock_app.notify = Mock()
        mock_app.copy_to_clipboard = Mock()

        # Mock the log's text_selection property to return our mock
        with patch.object(type(log), 'text_selection', new_callable=lambda: property(lambda self: mock_selection)):
            with patch('swecli.ui_textual.utils.clipboard._copy_osc52'):
                copy_selection_to_clipboard(mock_app)

        # Should notify on successful copy
        mock_app.notify.assert_called_once()
        call_args = mock_app.notify.call_args
        assert "copied to clipboard" in call_args[0][0]


class TestWidgetBasedSelection:
    """Tests for widget-based text selection (V2 architecture)."""

    def test_no_markup_static_has_allow_select(self):
        """Verify NoMarkupStatic has ALLOW_SELECT = True."""
        from swecli.ui_textual.widgets.messages import NoMarkupStatic

        assert NoMarkupStatic.ALLOW_SELECT is True, \
            "NoMarkupStatic should have ALLOW_SELECT = True for text selection"

        # Also verify on instance
        widget = NoMarkupStatic("test content")
        assert widget.ALLOW_SELECT is True

    def test_no_markup_static_can_focus(self):
        """Verify NoMarkupStatic has can_focus = True for receiving mouse events."""
        from swecli.ui_textual.widgets.messages import NoMarkupStatic

        assert NoMarkupStatic.can_focus is True, \
            "NoMarkupStatic should have can_focus = True for text selection"

        widget = NoMarkupStatic("test content")
        assert widget.can_focus is True

    def test_no_markup_static_allow_select_property(self):
        """Verify NoMarkupStatic.allow_select property returns True."""
        from swecli.ui_textual.widgets.messages import NoMarkupStatic

        widget = NoMarkupStatic("test content")
        # The property should return True regardless of is_container
        assert widget.allow_select is True, \
            "NoMarkupStatic.allow_select property should return True"

    def test_selectable_markdown_has_allow_select(self):
        """Verify SelectableMarkdown has ALLOW_SELECT = True."""
        from swecli.ui_textual.widgets.messages import SelectableMarkdown

        assert SelectableMarkdown.ALLOW_SELECT is True, \
            "SelectableMarkdown should have ALLOW_SELECT = True for text selection"

    def test_selectable_markdown_can_focus(self):
        """Verify SelectableMarkdown has can_focus = True for receiving mouse events."""
        from swecli.ui_textual.widgets.messages import SelectableMarkdown

        assert SelectableMarkdown.can_focus is True, \
            "SelectableMarkdown should have can_focus = True for text selection"

    def test_selectable_markdown_allow_select_property(self):
        """Verify SelectableMarkdown.allow_select property returns True."""
        from swecli.ui_textual.widgets.messages import SelectableMarkdown

        widget = SelectableMarkdown("")
        # The property should return True regardless of is_container
        assert widget.allow_select is True, \
            "SelectableMarkdown.allow_select property should return True"

    def test_non_selectable_static_blocks_selection(self):
        """Verify NonSelectableStatic properly blocks selection."""
        from swecli.ui_textual.widgets.messages import NonSelectableStatic

        widget = NonSelectableStatic("chrome text")
        assert widget.text_selection is None, \
            "NonSelectableStatic should return None for text_selection"

    def test_non_selectable_static_cannot_focus(self):
        """Verify NonSelectableStatic has can_focus = False."""
        from swecli.ui_textual.widgets.messages import NonSelectableStatic

        assert NonSelectableStatic.can_focus is False, \
            "NonSelectableStatic should have can_focus = False"

        widget = NonSelectableStatic("chrome text")
        assert widget.can_focus is False

    def test_non_selectable_static_allow_select_property(self):
        """Verify NonSelectableStatic.allow_select property returns False."""
        from swecli.ui_textual.widgets.messages import NonSelectableStatic

        widget = NonSelectableStatic("chrome text")
        # The property should return False to block selection
        assert widget.allow_select is False, \
            "NonSelectableStatic.allow_select property should return False"

    def test_conversation_log_v2_has_allow_select(self):
        """Verify ConversationLogV2 has ALLOW_SELECT = True."""
        from swecli.ui_textual.widgets.conversation_log_v2 import ConversationLogV2

        assert ConversationLogV2.ALLOW_SELECT is True, \
            "ConversationLogV2 should have ALLOW_SELECT = True"

    def test_feature_flag_switches_implementation(self):
        """Verify USE_WIDGET_LOG flag controls which ConversationLog is used."""
        import os
        from importlib import reload

        # Test with flag disabled (default)
        os.environ["SWECLI_USE_WIDGET_LOG"] = "0"
        from swecli.ui_textual.widgets import conversation_log
        from swecli.ui_textual import widgets
        reload(widgets)
        from swecli.ui_textual.widgets import ConversationLog as CL0
        assert CL0.__module__.endswith('conversation_log'), \
            "With USE_WIDGET_LOG=0, should use conversation_log module"

        # Test with flag enabled
        os.environ["SWECLI_USE_WIDGET_LOG"] = "1"
        reload(widgets)
        from swecli.ui_textual.widgets import ConversationLog as CL1
        assert CL1.__module__.endswith('conversation_log_v2'), \
            "With USE_WIDGET_LOG=1, should use conversation_log_v2 module"

        # Reset to default
        os.environ["SWECLI_USE_WIDGET_LOG"] = "0"
        reload(widgets)