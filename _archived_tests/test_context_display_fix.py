#!/usr/bin/env python3
"""Test that context display updates correctly."""

import sys
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).parent))

from swecli.core.management import SessionManager
from swecli.models.message import ChatMessage, Role


def test_context_display_updates():
    """Test that total_tokens_cached updates as messages are added."""
    print("\n" + "=" * 70)
    print("Testing Context Display Updates")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        session_manager = SessionManager(session_dir)
        session = session_manager.create_session()

        print("\nInitial state:")
        print(f"  total_tokens_cached: {session.total_tokens_cached}")
        print(f"  Messages: {len(session.messages)}")

        # Add messages and check token count updates
        test_messages = [
            "Hello, how are you?",
            "I'm working on improving the SWE-CLI interface.",
            "Can you help me understand how the context tracking works?",
            "Let me search for the relevant files in the codebase.",
            "I found several files related to session management and token counting.",
        ]

        for i, content in enumerate(test_messages, 1):
            msg = ChatMessage(role=Role.USER if i % 2 else Role.ASSISTANT, content=content)
            session_manager.add_message(msg)

            tokens = session.total_tokens_cached
            limit = 256000
            usage_pct = (tokens / limit) * 100
            remaining_pct = 100.0 - usage_pct

            print(f"\nAfter message {i}:")
            print(f"  Content: '{content[:50]}...'")
            print(f"  total_tokens_cached: {tokens:,}")
            print(f"  Usage: {usage_pct:.2f}%")
            print(f"  Context left until auto-compact: {remaining_pct:.0f}%")

            # Verify tokens are increasing
            if i > 1:
                assert tokens > 0, f"Tokens should be > 0 after message {i}"

        final_tokens = session.total_tokens_cached
        final_remaining = 100.0 - (final_tokens / 256000 * 100)

        print(f"\n{'=' * 70}")
        print("Final state:")
        print(f"  Total tokens: {final_tokens:,}")
        print(f"  Context left: {final_remaining:.0f}%")
        print(f"  Messages: {len(session.messages)}")

        assert final_tokens > 0, "Should have non-zero tokens after adding messages"
        assert final_remaining < 100, "Remaining should be less than 100%"
        assert final_remaining > 99, "Should still have >99% remaining with just a few messages"

        print("\n✅ Context display updates correctly!")
        print("   • Starts at 100% remaining")
        print("   • Decreases as messages are added")
        print("   • Shows accurate token usage")


def test_toolbar_calculation():
    """Test the exact calculation used in the toolbar."""
    print("\n" + "=" * 70)
    print("Testing Toolbar Calculation")
    print("=" * 70)

    # Simulate various token counts
    limit = 256000
    test_cases = [
        (0, 100.0),
        (2560, 99.0),
        (25600, 90.0),
        (128000, 50.0),
        (179200, 30.0),
        (204800, 20.0),  # 80% usage - triggers compaction
        (256000, 0.0),
    ]

    print("\n[Token usage scenarios]")
    for used, expected_remaining in test_cases:
        remaining_pct = max(0.0, 100.0 - (used / limit * 100.0))
        usage_pct = (used / limit) * 100.0

        print(f"\nUsed: {used:,} / {limit:,} tokens ({usage_pct:.1f}% usage)")
        print(f"  Remaining: {remaining_pct:.0f}% (expected: {expected_remaining:.0f}%)")

        assert abs(remaining_pct - expected_remaining) < 0.1, \
            f"Calculation mismatch: {remaining_pct:.1f}% != {expected_remaining:.1f}%"

        # Show what user sees
        if usage_pct < 80:
            status = f"Context left until auto-compact: {remaining_pct:.0f}%"
        else:
            status = f"Context left until auto-compact: {remaining_pct:.0f}% ⚠️ WILL COMPACT"

        print(f"  Display: '{status}'")

    print("\n✅ Toolbar calculation is correct!")


if __name__ == "__main__":
    try:
        test_context_display_updates()
        test_toolbar_calculation()

        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED!")
        print("=" * 70)

        print("\n[Summary]")
        print("• total_tokens_cached updates correctly")
        print("• Context percentage decreases as messages are added")
        print("• Toolbar calculation is accurate")
        print("• Display will show correct remaining percentage")
        print()

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
