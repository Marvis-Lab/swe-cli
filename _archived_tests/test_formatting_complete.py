#!/usr/bin/env python3
"""Complete test of formatting fixes for chat interface."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from swecli.repl.repl_chat import create_repl_chat
from swecli.core.management import ConfigManager
from swecli.core.management import SessionManager
from swecli.ui.rich_to_text import rich_to_text_box
from rich.panel import Panel


def test_text_wrapping():
    """Test text wrapping functionality."""
    print("=" * 80)
    print("TEST 1: Text Wrapping")
    print("=" * 80)

    config_manager = ConfigManager()
    config = config_manager.get_config()
    session_dir = Path(config.session_dir).expanduser()
    session_manager = SessionManager(session_dir)
    session_manager.create_session(working_directory=str(Path.cwd()))

    chat_repl = create_repl_chat(config_manager, session_manager)

    # Test long text
    long_text = (
        "This is a very long line of text that should be wrapped properly to fit "
        "within the 76 character width limit without breaking in the middle of words "
        "or creating any formatting issues whatsoever."
    )

    wrapped = chat_repl._wrap_text(long_text, width=76)
    print("\nOriginal text length:", len(long_text))
    print("\nWrapped text:")
    max_len = 0
    for i, line in enumerate(wrapped.split('\n')):
        print(f"  Line {i+1} ({len(line):2d} chars): {line}")
        max_len = max(max_len, len(line))

    if max_len <= 76:
        print(f"\n✅ PASS: All lines ≤76 characters (max: {max_len})")
        return True
    else:
        print(f"\n❌ FAIL: Some lines exceed 76 characters (max: {max_len})")
        return False


def test_rich_conversion():
    """Test Rich Panel to text conversion."""
    print("\n" + "=" * 80)
    print("TEST 2: Rich Panel Conversion")
    print("=" * 80)

    # Create test panel
    panel = Panel(
        "This is a test message inside a Rich panel.\n"
        "It should be converted to plain text with box drawing characters.\n"
        "ANSI codes should be removed.",
        title="Test Panel",
        border_style="blue"
    )

    text_box = rich_to_text_box(panel, width=78)
    print("\nConverted panel:")
    print(text_box)

    # Check for ANSI codes
    has_ansi = '\x1B' in text_box or '\033' in text_box

    # Check width
    max_len = max(len(line) for line in text_box.split('\n'))

    print(f"\nANSI codes removed: {'❌ FAIL' if has_ansi else '✅ PASS'}")
    print(f"Max line length: {max_len} chars {'✅ PASS' if max_len <= 78 else '❌ FAIL'}")

    return not has_ansi and max_len <= 78


def test_welcome_message():
    """Test welcome message formatting."""
    print("\n" + "=" * 80)
    print("TEST 3: Welcome Message")
    print("=" * 80)

    config_manager = ConfigManager()
    config = config_manager.get_config()
    session_dir = Path(config.session_dir).expanduser()
    session_manager = SessionManager(session_dir)
    session_manager.create_session(working_directory=str(Path.cwd()))

    chat_repl = create_repl_chat(config_manager, session_manager)

    print("\nWelcome message content:")
    print("-" * 80)

    max_len = 0
    too_long = []

    for i, (role, content, timestamp) in enumerate(chat_repl.conversation.messages):
        for line in content.split('\n'):
            print(line)
            if len(line) > 78:
                too_long.append((i+1, len(line), line[:50] + "..."))
            max_len = max(max_len, len(line))

    print("-" * 80)
    print(f"\nTotal messages: {len(chat_repl.conversation.messages)}")
    print(f"Max line length: {max_len} chars")

    if too_long:
        print(f"\n❌ FAIL: {len(too_long)} lines exceed 78 characters:")
        for msg_num, length, preview in too_long:
            print(f"  Message {msg_num}: {length} chars - {preview}")
        return False
    else:
        print("\n✅ PASS: All lines ≤78 characters")
        return True


def test_multi_paragraph():
    """Test multi-paragraph text wrapping."""
    print("\n" + "=" * 80)
    print("TEST 4: Multi-Paragraph Wrapping")
    print("=" * 80)

    config_manager = ConfigManager()
    config = config_manager.get_config()
    session_dir = Path(config.session_dir).expanduser()
    session_manager = SessionManager(session_dir)
    session_manager.create_session(working_directory=str(Path.cwd()))

    chat_repl = create_repl_chat(config_manager, session_manager)

    multi_para = (
        "First paragraph is short.\n\n"
        "Second paragraph is very long and needs to be wrapped because it exceeds "
        "the maximum width we have set for proper display in the chat interface "
        "without breaking words.\n\n"
        "Third paragraph is also short."
    )

    wrapped = chat_repl._wrap_text(multi_para, width=76)
    print("\nWrapped multi-paragraph text:")

    max_len = 0
    for i, line in enumerate(wrapped.split('\n')):
        print(f"  Line {i+1:2d} ({len(line):2d} chars): {line}")
        max_len = max(max_len, len(line))

    # Check paragraphs preserved
    paragraphs = wrapped.split('\n\n')

    if max_len <= 76 and len(paragraphs) == 3:
        print(f"\n✅ PASS: Paragraphs preserved and lines ≤76 chars (max: {max_len})")
        return True
    else:
        print("\n❌ FAIL: Issue with wrapping or paragraph preservation")
        return False


def main():
    """Run all formatting tests."""
    print("\n" + "=" * 80)
    print("OPENCLI CHAT FORMATTING TESTS")
    print("=" * 80)

    results = []

    try:
        results.append(("Text Wrapping", test_text_wrapping()))
        results.append(("Rich Conversion", test_rich_conversion()))
        results.append(("Welcome Message", test_welcome_message()))
        results.append(("Multi-Paragraph", test_multi_paragraph()))
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")

    total = len(results)
    passed = sum(1 for _, p in results if p)

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED - Formatting fixes complete!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
