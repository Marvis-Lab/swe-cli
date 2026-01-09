"""Reusable Textual widgets for the SWE-CLI UI."""

import os

# Feature flag to switch between RichLog-based and VerticalScroll-based ConversationLog
# Default is now widget-based (V2) for text selection support
# Set SWECLI_USE_WIDGET_LOG=0 to use the old RichLog-based implementation
USE_WIDGET_LOG = os.environ.get("SWECLI_USE_WIDGET_LOG", "1") == "1"

if USE_WIDGET_LOG:
    from .conversation_log_v2 import ConversationLogV2 as ConversationLog
else:
    from .conversation_log import ConversationLog

from .chat_text_area import ChatTextArea
from .status_bar import ModelFooter, StatusBar

__all__ = ["ConversationLog", "ChatTextArea", "StatusBar", "ModelFooter"]
