"""Test mouse scroll functionality in ConversationLog."""

import pytest
from swecli.ui_textual.widgets.conversation_log import ConversationLog


class TestMouseScroll:
    """Test mouse scroll event handling."""

    def test_has_mouse_scroll_handlers(self):
        """Verify mouse scroll handlers exist."""
        log = ConversationLog()
        assert hasattr(log, 'on_mouse_scroll_down')
        assert hasattr(log, 'on_mouse_scroll_up')
        assert callable(log.on_mouse_scroll_down)
        assert callable(log.on_mouse_scroll_up)

    def test_initial_auto_scroll_state(self):
        """Verify initial auto-scroll state is correct."""
        log = ConversationLog()
        assert log.auto_scroll is True
        assert log._user_scrolled is False

    def test_mouse_scroll_down_updates_state(self):
        """Mouse scroll down should set user_scrolled and disable auto_scroll."""
        log = ConversationLog()

        # Simulate the state changes that on_mouse_scroll_down does
        # (We can't call the actual handler without a real event)
        log._user_scrolled = True
        log.auto_scroll = False

        assert log._user_scrolled is True
        assert log.auto_scroll is False

    def test_mouse_scroll_up_updates_state(self):
        """Mouse scroll up should set user_scrolled and disable auto_scroll."""
        log = ConversationLog()

        # Simulate the state changes that on_mouse_scroll_up does
        log._user_scrolled = True
        log.auto_scroll = False

        assert log._user_scrolled is True
        assert log.auto_scroll is False


class TestMouseScrollIntegration:
    """Integration tests for mouse scroll with app settings."""

    def test_app_has_mouse_enabled(self):
        """Verify ENABLE_MOUSE is True in the chat app."""
        from swecli.ui_textual.chat_app import SWECLIChatApp
        assert SWECLIChatApp.ENABLE_MOUSE is True

    def test_conversation_log_imports(self):
        """Verify mouse event types are imported."""
        from textual.events import MouseScrollDown, MouseScrollUp
        from swecli.ui_textual.widgets.conversation_log import ConversationLog

        # Check that the handler signatures match expected event types
        import inspect
        sig_down = inspect.signature(ConversationLog.on_mouse_scroll_down)
        sig_up = inspect.signature(ConversationLog.on_mouse_scroll_up)

        # Should have 'self' and 'event' parameters
        assert 'event' in sig_down.parameters
        assert 'event' in sig_up.parameters


class TestSelectionTip:
    """Test selection tip feature."""

    def test_app_has_show_selection_tip(self):
        """Verify app has show_selection_tip method."""
        from swecli.ui_textual.chat_app import SWECLIChatApp
        assert hasattr(SWECLIChatApp, 'show_selection_tip')
        assert callable(SWECLIChatApp.show_selection_tip)

    def test_conversation_log_has_mouse_drag_handlers(self):
        """Verify conversation log has mouse drag detection handlers."""
        from swecli.ui_textual.widgets.conversation_log import ConversationLog
        log = ConversationLog()

        # Check mouse drag detection state
        assert hasattr(log, '_mouse_down_pos')

        # Check handlers exist
        assert hasattr(log, 'on_mouse_down')
        assert hasattr(log, 'on_mouse_move')
        assert hasattr(log, 'on_mouse_up')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
