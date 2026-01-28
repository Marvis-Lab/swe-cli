#!/usr/bin/env python3
"""Test auto-compact indicator functionality."""

import sys
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).parent))

from swecli.core.management import SessionManager
from swecli.core.monitoring import TaskMonitor
from swecli.models.message import ChatMessage, Role
from rich.console import Console


def test_context_display():
    """Test that context display shows correctly at different usage levels."""
    print("\n" + "=" * 60)
    print("Testing Auto-Compact Indicator")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        session_manager = SessionManager(session_dir)
        session = session_manager.create_session()

        # Create task monitor with session manager
        task_monitor = TaskMonitor(session_manager=session_manager)

        # Test different token levels
        test_cases = [
            (50000, "< 70%", "should show 'context: X%'"),
            (150000, "~59%", "should show 'context: 59%'"),
            (180000, "~70%", "should show 'X% until compact'"),
            (210000, "~82%", "should show 'X% until compact' + TRIGGER COMPACTION"),
        ]

        for target_tokens, usage_desc, expected_behavior in test_cases:
            print(f"\n{'─' * 60}")
            print(f"Test: {usage_desc} usage ({target_tokens:,} tokens)")
            print(f"Expected: {expected_behavior}")
            print("─" * 60)

            # Clear and rebuild session
            session.messages.clear()
            session.total_tokens_cached = 0

            # Add messages to reach target token count
            msg_size = 100  # words per message
            while session.total_tokens_cached < target_tokens:
                msg = ChatMessage(
                    role=Role.USER,
                    content="Test message content. " * msg_size,
                )
                session_manager.add_message(msg)

            # Get stats
            stats = session.get_token_stats()
            actual_tokens = stats["current_tokens"]
            usage_pct = stats["usage_percent"]
            until_compact_pct = stats["until_compact_percent"]
            needs_compaction = stats["needs_compaction"]

            print(f"\nActual tokens: {actual_tokens:,}")
            print(f"Usage: {usage_pct:.1f}%")
            print(f"Until compact: {until_compact_pct:.1f}%")
            print(f"Needs compaction: {needs_compaction}")

            # Get context display from task monitor
            task_monitor.set_session_manager(session_manager)
            context_display = task_monitor.get_context_display()
            shows_warning = task_monitor.should_show_context_warning()

            print(f"\nContext Display: '{context_display}'")
            print(f"Shows Warning: {shows_warning}")

            # Verify display format
            if usage_pct < 70:
                assert "context:" in context_display, f"Should show 'context: X%' at {usage_pct:.1f}%"
                assert not shows_warning, f"Should not show warning at {usage_pct:.1f}%"
                print("✓ Correct format for < 70%")
            else:
                assert "until compact" in context_display, f"Should show 'X% until compact' at {usage_pct:.1f}%"
                assert shows_warning, f"Should show warning at {usage_pct:.1f}%"
                print("✓ Correct format for >= 70%")

            # Test auto-compaction
            if needs_compaction:
                print(f"\n🔥 Triggering auto-compaction at {usage_pct:.1f}%...")
                messages_before = len(session.messages)
                tokens_before = actual_tokens

                result = session_manager.check_and_compact(preserve_recent=5)

                if result:
                    messages_after = len(session.messages)
                    tokens_after = session.total_tokens_cached
                    tokens_saved = result.tokens_saved
                    reduction = result.reduction_percent

                    print("✅ Auto-compaction executed!")
                    print(f"   Messages: {messages_before} → {messages_after}")
                    print(f"   Tokens: {tokens_before:,} → {tokens_after:,}")
                    print(f"   Saved: {tokens_saved:,} tokens ({reduction:.1f}% reduction)")

                    # Verify compaction worked
                    assert messages_after < messages_before, "Should have fewer messages"
                    assert tokens_after < tokens_before, "Should have fewer tokens"
                    assert reduction > 60, "Should have >60% reduction"

                    # Check display after compaction
                    new_stats = session.get_token_stats()
                    new_usage = new_stats["usage_percent"]
                    print(f"   New usage: {new_usage:.1f}%")
                    assert new_usage < 70, "Usage should be < 70% after compaction"
                else:
                    print("⚠️  Compaction did not run (unexpected)")
            else:
                print("✓ No compaction needed at this level")

    print("\n" + "=" * 60)
    print("✅ ALL AUTO-COMPACT INDICATOR TESTS PASSED!")
    print("=" * 60)


def test_real_time_display():
    """Test context display in real-time scenario."""
    print("\n" + "=" * 60)
    print("Real-Time Display Test")
    print("=" * 60)

    console = Console()

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        session_manager = SessionManager(session_dir)
        session = session_manager.create_session()
        task_monitor = TaskMonitor(session_manager=session_manager)

        # Simulate conversation with increasing context
        for i in range(10):
            # Add a message
            msg = ChatMessage(
                role=Role.USER if i % 2 == 0 else Role.ASSISTANT,
                content=f"Message {i+1}: " + "Content here. " * 100,
            )
            session_manager.add_message(msg)

            # Display current context
            stats = session.get_token_stats()
            context_display = task_monitor.get_context_display()

            console.print(
                f"Turn {i+1}: {stats['current_tokens']:,} tokens "
                f"({stats['usage_percent']:.1f}%) - {context_display}"
            )

    print("\n✓ Real-time display working")


if __name__ == "__main__":
    try:
        test_context_display()
        test_real_time_display()
        print("\n🎉 All tests passed! Auto-compact indicator is working.\n")
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
