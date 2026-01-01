#!/usr/bin/env python3
"""Test the current state of the chat interface after revert."""

import sys
from pathlib import Path

# Add opencli to path
sys.path.insert(0, str(Path(__file__).parent))

from swecli.ui.chat_app import ChatApplication
from swecli.ui.chat_formatters import ChatBoxFormatter

print("Testing Current State of Chat Interface")
print("=" * 60)

# Test 1: Can we create the application?
try:
    chat = ChatApplication()
    print("✓ ChatApplication created successfully")
except Exception as e:
    print(f"✗ Failed to create ChatApplication: {e}")
    sys.exit(1)

# Test 2: Check what control is being used
print(f"\n✓ Using control type: {type(chat.conversation_control).__name__}")

# Test 3: Add various types of messages
print("\nAdding test messages...")
formatter = ChatBoxFormatter()

# Add user message
chat.conversation.add_user_message("list files in current directory")
print("  ✓ Added user message")

# Add tool call box
tool_box = formatter.tool_call_box("list_files", {"path": "."})
chat.add_assistant_message(tool_box)
print("  ✓ Added tool call box")

# Add result box
result_box = formatter.success_result_box("list_files", "file1.py\nfile2.txt\nfolder/")
chat.add_assistant_message(result_box)
print("  ✓ Added result box")

# Add LLM response
chat.add_assistant_message("⏺ I found 3 items in the current directory.")
print("  ✓ Added LLM response")

# Add more messages to test scrolling
print("\nAdding more messages to test scrolling...")
for i in range(5):
    chat.conversation.add_user_message(f"Test command {i}")
    tool_box = formatter.tool_call_box("test_tool", {"index": str(i)})
    chat.add_assistant_message(tool_box)
    result_box = formatter.success_result_box("test_tool", f"Result {i}")
    chat.add_assistant_message(result_box)

print(f"✓ Total messages: {len(chat.conversation.messages)}")

# Test 4: Check if ANSI codes are in the output
plain_text = chat.conversation.get_plain_text()
has_ansi = '\033[' in plain_text
has_boxes = '┌' in plain_text and '│' in plain_text
print(f"\n✓ ANSI codes present: {has_ansi}")
print(f"✓ Box characters present: {has_boxes}")
print(f"✓ Total lines: {plain_text.count(chr(10))}")

# Test 5: Check scroll control functionality
print("\n" + "=" * 60)
print("Scroll Control Tests:")
print("=" * 60)

# Check initial scroll state
print(f"Initial scroll offset: {chat.conversation_control.scroll_offset}")
print(f"Auto-scroll enabled: {chat.conversation_control._auto_scroll}")

# Test create_content to see if it renders
try:
    # Simulate a window size
    content = chat.conversation_control.create_content(width=80, height=20)
    print(f"✓ create_content() works - line_count: {content.line_count}")

    # Check scroll after rendering
    print(f"Scroll offset after render: {chat.conversation_control.scroll_offset}")

    # Try scrolling manually
    chat.conversation_control.move_cursor_up()
    print(f"After move_cursor_up: {chat.conversation_control.scroll_offset}")
    print(f"Auto-scroll disabled: {not chat.conversation_control._auto_scroll}")

    # Try scroll to bottom
    chat.conversation_control.scroll_to_bottom()
    print(f"After scroll_to_bottom: {chat.conversation_control.scroll_offset}")
    print(f"Auto-scroll enabled: {chat.conversation_control._auto_scroll}")

    # Render again to see the scroll offset update
    content2 = chat.conversation_control.create_content(width=80, height=20)
    print(f"Scroll offset after second render: {chat.conversation_control.scroll_offset}")

except Exception as e:
    print(f"✗ Error testing scroll: {e}")
    import traceback
    traceback.print_exc()

# Test 6: Check layout structure
print("\n" + "=" * 60)
print("Layout Structure:")
print("=" * 60)
print(f"Layout type: {type(chat.layout)}")
print(f"Root container: {type(chat.layout.container)}")

# Check if HSplit is used
from prompt_toolkit.layout.containers import HSplit
if isinstance(chat.layout.container, HSplit):
    print(f"✓ Using HSplit with {len(chat.layout.container.children)} children:")
    for i, child in enumerate(chat.layout.container.children):
        print(f"  {i+1}. {type(child).__name__}")
        if hasattr(child, 'height'):
            print(f"     Height: {child.height}")

# Final summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

working = []
issues = []

if has_ansi and has_boxes:
    working.append("ANSI colors and box formatting")
else:
    issues.append("ANSI rendering")

if chat.conversation_control.scroll_offset > 0:
    working.append("Auto-scroll to bottom")
else:
    issues.append("Auto-scroll not positioning correctly")

if isinstance(chat.layout.container, HSplit):
    working.append("Split-screen layout structure")

print("\n✓ WORKING:")
for item in working:
    print(f"  • {item}")

if issues:
    print("\n⚠ POTENTIAL ISSUES:")
    for item in issues:
        print(f"  • {item}")

print("\n" + "=" * 60)
print("Ready to test in actual REPL by running: python -m opencli")
print("=" * 60)
