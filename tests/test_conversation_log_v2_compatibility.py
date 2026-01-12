"""Tests ensuring ConversationLogV2 is compatible with V1 renderer patterns.

These tests verify that the VirtualLineList properly intercepts all list operations
so that message_renderer, tool_renderer, spinner_manager, and spinner_service
work correctly with the widget-based V2 architecture.
"""

import pytest
from unittest.mock import Mock, MagicMock
from rich.text import Text


def _create_mock_widget(content):
    """Create a properly configured mock widget.

    We use spec=[] to prevent auto-creation of attributes,
    then explicitly set only the attributes we want.
    """
    mock_widget = Mock(spec=[])
    # Use content property (like real Static widgets)
    mock_widget.content = content
    return mock_widget


class TestVirtualLine:
    """Tests for the VirtualLine wrapper class."""

    def test_plain_from_text(self):
        """Test .plain extracts text from Rich Text."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLine

        mock_widget = _create_mock_widget(Text("hello world"))
        vline = VirtualLine(mock_widget)
        assert vline.plain == "hello world"

    def test_plain_from_string(self):
        """Test .plain handles string content."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLine

        mock_widget = _create_mock_widget("plain string")
        vline = VirtualLine(mock_widget)
        assert vline.plain == "plain string"

    def test_plain_from_none(self):
        """Test .plain handles None content."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLine

        mock_widget = _create_mock_widget(None)
        vline = VirtualLine(mock_widget)
        assert vline.plain == ""

    def test_plain_from_empty_string(self):
        """Test .plain handles empty string."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLine

        mock_widget = _create_mock_widget("")
        vline = VirtualLine(mock_widget)
        assert vline.plain == ""

    def test_text_alias(self):
        """Test .text is alias for .plain."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLine

        mock_widget = _create_mock_widget(Text("test content"))
        vline = VirtualLine(mock_widget)
        assert vline.text == vline.plain
        assert vline.text == "test content"

    def test_str(self):
        """Test __str__ returns plain text."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLine

        mock_widget = _create_mock_widget(Text("string test"))
        vline = VirtualLine(mock_widget)
        assert str(vline) == "string test"


class TestVirtualLineList:
    """Tests for the VirtualLineList class."""

    def test_len_empty(self):
        """Test __len__ on empty list."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList

        vll = VirtualLineList(None)
        assert len(vll) == 0

    def test_len_nonempty(self):
        """Test __len__ with items."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        mock_widget = Mock()
        vll.append(VirtualLine(mock_widget))
        assert len(vll) == 1

        vll.append(VirtualLine(Mock()))
        assert len(vll) == 2

    def test_bool_empty(self):
        """Test empty list is falsy."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList

        vll = VirtualLineList(None)
        assert not vll
        assert bool(vll) is False

    def test_bool_nonempty(self):
        """Test non-empty list is truthy."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        mock_widget = Mock()
        vll.append(VirtualLine(mock_widget))
        assert vll
        assert bool(vll) is True

    def test_getitem_index(self):
        """Test __getitem__ with integer index."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        mock_widget = Mock()
        vline = VirtualLine(mock_widget)
        vll.append(vline)

        assert vll[0] is vline
        assert vll[-1] is vline

    def test_getitem_slice(self):
        """Test __getitem__ with slice."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        vlines = [VirtualLine(Mock()) for _ in range(3)]
        for vline in vlines:
            vll.append(vline)

        result = vll[1:]
        assert len(result) == 2
        assert result[0] is vlines[1]
        assert result[1] is vlines[2]

    def test_setitem_updates_widget(self):
        """Test __setitem__ updates the widget content."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        mock_widget = Mock()
        vll.append(VirtualLine(mock_widget))

        new_text = Text("updated")
        vll[0] = new_text
        mock_widget.update.assert_called_once_with(new_text)

    def test_setitem_negative_index(self):
        """Test __setitem__ with negative index."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        mock_widget = Mock()
        vll.append(VirtualLine(mock_widget))

        new_text = Text("updated via -1")
        vll[-1] = new_text
        mock_widget.update.assert_called_once_with(new_text)

    def test_setitem_strip_conversion(self):
        """Test __setitem__ converts Strip to Text."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine
        from rich.segment import Segment

        vll = VirtualLineList(None)
        mock_widget = Mock()
        vll.append(VirtualLine(mock_widget))

        # Create a mock Strip-like object
        mock_strip = MagicMock()
        mock_strip.__iter__ = Mock(return_value=iter([Segment("hello", "bold")]))
        mock_strip.cell_length = Mock(return_value=5)

        vll[0] = mock_strip

        # Should have called update with a Text object
        mock_widget.update.assert_called_once()
        call_arg = mock_widget.update.call_args[0][0]
        assert isinstance(call_arg, Text)
        assert call_arg.plain == "hello"

    def test_delitem_single(self):
        """Test del vll[idx] removes widget."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        mock_widget = Mock()
        vll.append(VirtualLine(mock_widget))

        del vll[0]
        assert len(vll) == 0
        mock_widget.remove.assert_called_once()

    def test_delitem_negative(self):
        """Test del vll[-1] works."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        widgets = [Mock() for _ in range(3)]
        for w in widgets:
            vll.append(VirtualLine(w))

        del vll[-1]
        assert len(vll) == 2
        widgets[2].remove.assert_called_once()
        widgets[0].remove.assert_not_called()
        widgets[1].remove.assert_not_called()

    def test_delitem_slice(self):
        """Test del vll[start:] removes multiple widgets."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)

        widgets = [Mock() for _ in range(3)]
        for w in widgets:
            vll.append(VirtualLine(w))

        del vll[1:]
        assert len(vll) == 1
        widgets[1].remove.assert_called_once()
        widgets[2].remove.assert_called_once()
        widgets[0].remove.assert_not_called()

    def test_delitem_slice_middle(self):
        """Test del vll[1:3] removes specific range."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)

        widgets = [Mock() for _ in range(5)]
        for w in widgets:
            vll.append(VirtualLine(w))

        del vll[1:3]
        assert len(vll) == 3
        widgets[0].remove.assert_not_called()
        widgets[1].remove.assert_called_once()
        widgets[2].remove.assert_called_once()
        widgets[3].remove.assert_not_called()
        widgets[4].remove.assert_not_called()

    def test_iter(self):
        """Test iteration over lines."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        vlines = [VirtualLine(Mock()) for _ in range(3)]
        for vline in vlines:
            vll.append(vline)

        iterated = list(vll)
        assert iterated == vlines

    def test_insert(self):
        """Test insert at specific position."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        first = VirtualLine(Mock())
        third = VirtualLine(Mock())
        vll.append(first)
        vll.append(third)

        second = VirtualLine(Mock())
        vll.insert(1, second)

        assert len(vll) == 3
        assert vll[0] is first
        assert vll[1] is second
        assert vll[2] is third

    def test_clear(self):
        """Test clear removes all widgets."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        widgets = [Mock() for _ in range(3)]
        for w in widgets:
            vll.append(VirtualLine(w))

        vll.clear()
        assert len(vll) == 0
        for w in widgets:
            w.remove.assert_called_once()


class TestRendererPatterns:
    """Tests ensuring common renderer patterns work with VirtualLineList."""

    def test_spacing_check_pattern_empty(self):
        """Test pattern: if self.log.lines and self.log.lines[-1].plain.strip()

        This pattern is used by message_renderer to add spacing before messages.
        When lines is empty, the condition should short-circuit.
        """
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList

        vll = VirtualLineList(None)

        # This should not raise IndexError because it short-circuits
        result = vll and vll[-1].plain.strip()
        assert not result

    def test_spacing_check_pattern_with_content(self):
        """Test spacing check pattern with content."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        mock_widget = _create_mock_widget(Text("content"))
        vll.append(VirtualLine(mock_widget))

        result = vll and vll[-1].plain.strip()
        assert result == "content"

    def test_spacing_check_pattern_with_empty_last_line(self):
        """Test spacing check with empty last line (spacer)."""
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        mock_widget = _create_mock_widget(Text(""))  # Spacer line
        vll.append(VirtualLine(mock_widget))

        result = vll and vll[-1].plain.strip()
        assert not result  # Empty string is falsy

    def test_len_tracking_pattern(self):
        """Test pattern: self._tool_call_start = len(self.log.lines)

        This pattern is used by tool_renderer to track line positions.
        """
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)

        start = len(vll)
        assert start == 0

        # Add content
        mock_widget = Mock()
        vll.append(VirtualLine(mock_widget))

        new_len = len(vll)
        assert new_len == 1

    def test_inplace_update_pattern(self):
        """Test pattern: self.log.lines[idx] = strip

        This pattern is used for spinner animation updates.
        """
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        mock_widget = Mock()
        vll.append(VirtualLine(mock_widget))

        # Update in place
        vll[0] = Text("updated content")
        mock_widget.update.assert_called()

    def test_hasattr_plain_pattern(self):
        """Test pattern: hasattr(self.log.lines[-1], 'plain')

        This pattern is used by message_renderer for safe attribute access.
        """
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        mock_widget = _create_mock_widget(Text("test"))
        vll.append(VirtualLine(mock_widget))

        assert hasattr(vll[-1], "plain")
        assert vll[-1].plain == "test"

    def test_getattr_plain_pattern(self):
        """Test pattern: getattr(self.log.lines[-1], 'plain', '')

        This pattern is used by tool_renderer for safe attribute access.
        """
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        mock_widget = _create_mock_widget(Text("test content"))
        vll.append(VirtualLine(mock_widget))

        result = getattr(vll[-1], "plain", "")
        assert result == "test content"

    def test_delete_and_insert_pattern(self):
        """Test pattern: del lines[idx]; lines.insert(idx, strip)

        This pattern is used by spinner_manager for animation updates.
        """
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        original_widget = Mock()
        vll.append(VirtualLine(original_widget))

        # Delete at index
        del vll[0]
        original_widget.remove.assert_called_once()

        # Insert new content at same index
        new_widget = Mock()
        vll.insert(0, VirtualLine(new_widget))
        assert len(vll) == 1

    def test_range_deletion_pattern(self):
        """Test pattern: del self.log.lines[index:]

        This pattern is used by tool_renderer for truncation.
        """
        from swecli.ui_textual.widgets.conversation_log_v2 import VirtualLineList, VirtualLine

        vll = VirtualLineList(None)
        widgets = [Mock() for _ in range(5)]
        for w in widgets:
            vll.append(VirtualLine(w))

        del vll[2:]
        assert len(vll) == 2
        widgets[0].remove.assert_not_called()
        widgets[1].remove.assert_not_called()
        widgets[2].remove.assert_called_once()
        widgets[3].remove.assert_called_once()
        widgets[4].remove.assert_called_once()


class TestConversationLogV2Integration:
    """Integration tests for ConversationLogV2 with VirtualLineList."""

    def test_write_tracks_lines(self):
        """Test that write() adds to lines list."""
        from swecli.ui_textual.widgets.conversation_log_v2 import ConversationLogV2
        from textual.app import App

        # Create a mock app context
        log = ConversationLogV2()

        # Mock the mount method to avoid actual widget mounting
        mounted_widgets = []
        original_mount = log.mount

        def mock_mount(widget):
            mounted_widgets.append(widget)

        log.mount = mock_mount

        # Write content
        log.write(Text("line 1"))
        log.write(Text("line 2"))

        assert len(log.lines) == 2
        assert log.lines[0].plain == "line 1"
        assert log.lines[1].plain == "line 2"

    def test_write_empty_creates_spacer(self):
        """Test that write(Text('')) creates a spacer line."""
        from swecli.ui_textual.widgets.conversation_log_v2 import ConversationLogV2

        log = ConversationLogV2()
        log.mount = Mock()

        log.write(Text(""))

        assert len(log.lines) == 1
        assert log.lines[0].plain == ""

    def test_clear_resets_lines(self):
        """Test that clear() resets the lines list."""
        from swecli.ui_textual.widgets.conversation_log_v2 import ConversationLogV2

        log = ConversationLogV2()
        log.mount = Mock()

        log.write(Text("line 1"))
        log.write(Text("line 2"))
        assert len(log.lines) == 2

        # Mock children to avoid errors
        log._line_list._lines[0]._widget.remove = Mock()
        log._line_list._lines[1]._widget.remove = Mock()
        log._children = []

        @property
        def children_prop(self):
            return []

        type(log).children = children_prop

        log.clear()
        assert len(log.lines) == 0

    def test_lines_truthiness_after_write(self):
        """Test that log.lines is truthy after writing content."""
        from swecli.ui_textual.widgets.conversation_log_v2 import ConversationLogV2

        log = ConversationLogV2()
        log.mount = Mock()

        assert not log.lines  # Empty is falsy

        log.write(Text("content"))
        assert log.lines  # Has content is truthy

    def test_skip_renderable_storage_flag(self):
        """Test that _skip_renderable_storage prevents line tracking."""
        from swecli.ui_textual.widgets.conversation_log_v2 import ConversationLogV2

        log = ConversationLogV2()
        log.mount = Mock()

        # Normal write
        log.write(Text("tracked"))
        assert len(log.lines) == 1

        # Write with skip flag
        log._skip_renderable_storage = True
        log.write(Text("not tracked"))
        log._skip_renderable_storage = False

        # Only the first write should be tracked
        assert len(log.lines) == 1
        assert log.lines[0].plain == "tracked"
