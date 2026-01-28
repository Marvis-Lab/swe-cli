#!/usr/bin/env python3
"""Test if SWE-CLI starts without errors."""

import sys
from pathlib import Path

# Add opencli to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    print("Testing imports...")
    from swecli.ui.chat_app import ChatApplication
    from swecli.ui.chat_formatters import ChatBoxFormatter
    print("✓ All imports successful")

    print("\nTesting ChatApplication creation...")
    chat = ChatApplication()
    print("✓ ChatApplication created")

    print("\nTesting message operations...")
    chat.conversation.add_user_message("test")
    chat.conversation.add_assistant_message("response")
    chat.conversation.add_system_message("system")
    print(f"✓ Messages added: {len(chat.conversation.messages)} messages")

    print("\nTesting message formatting...")
    formatted = chat.conversation.get_formatted_text()
    print(f"✓ Formatted text generated: {len(formatted)} elements")

    print("\nTesting box formatter...")
    formatter = ChatBoxFormatter()
    box = formatter.tool_call_box("test_tool", {"arg": "value"})
    print(f"✓ Tool box created: {len(box)} chars")

    result_box = formatter.success_result_box("test_tool", "Success!")
    print(f"✓ Result box created: {len(result_box)} chars")

    print("\n✅ All tests passed! SWE-CLI should start properly.")
    sys.exit(0)

except Exception as e:
    print(f"\n❌ Test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
