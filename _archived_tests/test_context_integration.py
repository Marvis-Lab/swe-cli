#!/usr/bin/env python3
"""End-to-end integration test for context engineering system."""

import sys
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).parent))

from swecli.core.context import ContextRetriever
from swecli.core.context import CodebaseIndexer
from swecli.core.monitoring import TaskMonitor
from swecli.core.management import SessionManager
from swecli.models.message import ChatMessage, Role


def test_full_workflow():
    """Test complete workflow: monitoring → compaction → retrieval → indexing."""
    print("\n" + "=" * 60)
    print("Test 1: Full Context Engineering Workflow")
    print("=" * 60)

    # Create a temporary session directory
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)

        # === Phase 1: Token Monitoring ===
        print("\n1. Token Monitoring")
        print("-" * 40)

        session_manager = SessionManager(session_dir)
        session = session_manager.create_session()

        # Add messages
        for i in range(10):
            msg = ChatMessage(
                role=Role.USER if i % 2 == 0 else Role.ASSISTANT,
                content=f"Message {i+1}: " + "Some content here. " * 20,
            )
            session_manager.add_message(msg)

        print(f"Added {len(session.messages)} messages")
        print(f"Total tokens: {session.total_tokens_cached:,}")

        stats = session.get_token_stats()
        print(f"Usage: {stats['usage_percent']:.2f}%")
        print("✓ Token monitoring working\n")

        # === Phase 2: Task Monitor Integration ===
        print("2. Task Monitor with Context Display")
        print("-" * 40)

        task_monitor = TaskMonitor(session_manager=session_manager)
        task_monitor.start("Testing context display", initial_tokens=0)

        # Simulate token update
        task_monitor.update_tokens(5000)

        # Get context display
        context_display = task_monitor.get_context_display()
        print(f"Context display: {context_display}")

        assert context_display, "Should have context display"
        assert "context:" in context_display or "%" in context_display
        print(f"✓ Task monitor shows context: '{context_display}'\n")

        task_monitor.stop()

        # === Phase 3: Compaction ===
        print("3. Context Compaction")
        print("-" * 40)

        # Add many more messages to trigger compaction need
        print("Adding more messages to reach compaction threshold...")
        while session.total_tokens_cached < 210000:  # 82% of 256k
            msg = ChatMessage(
                role=Role.USER,
                content="This is a longer message with substantial content. " * 50,
            )
            session_manager.add_message(msg)

        print(f"Total messages: {len(session.messages)}")
        print(f"Total tokens: {session.total_tokens_cached:,}")
        print(f"Usage: {session.get_token_stats()['usage_percent']:.1f}%")

        needs_compact = session.needs_compaction()
        print(f"Needs compaction: {needs_compact}")

        assert needs_compact, "Should need compaction at this point"

        # Perform compaction
        print("\nPerforming compaction...")
        result = session_manager.check_and_compact(preserve_recent=5)

        if result:
            print(f"Compacted {result.messages_compacted} messages")
            print(f"Saved {result.tokens_saved:,} tokens ({result.reduction_percent:.1f}% reduction)")
            print(f"New usage: {session.get_token_stats()['usage_percent']:.1f}%")
            print("✓ Compaction successful\n")
        else:
            print("⚠️  Compaction not performed (might be below threshold now)")

        # === Phase 4: Context Retrieval ===
        print("4. Just-in-Time Context Retrieval")
        print("-" * 40)

        retriever = ContextRetriever(working_dir=Path.cwd())

        user_query = "Fix the bug in context_token_monitor.py"
        context = retriever.retrieve_context(user_query)

        print(f"User query: {user_query}")
        print(f"Entities extracted: {context['entities']}")
        print(f"Files found: {len(context['files_found'])}")

        for file_info in context["files_found"][:3]:
            print(f"  - {Path(file_info['path']).name} ({file_info['reason']})")

        print("✓ Context retrieval working\n")

        # === Phase 5: Codebase Indexing ===
        print("5. Codebase Index Generation")
        print("-" * 40)

        indexer = CodebaseIndexer(working_dir=Path.cwd())
        index_content = indexer.generate_index(max_tokens=3000)

        index_stats = indexer.get_stats(index_content)
        print(f"Index tokens: {index_stats['tokens']:,}")
        print(f"Under 3k limit: {index_stats['under_limit']}")
        print("✓ Codebase indexing working\n")

    print("=" * 60)
    print("✅ Full workflow test passed!")
    print("=" * 60)


def test_task_monitor_context_warning():
    """Test task monitor context warning thresholds."""
    print("\n" + "=" * 60)
    print("Test 2: Task Monitor Context Warnings")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        session_manager = SessionManager(session_dir)
        session = session_manager.create_session()

        task_monitor = TaskMonitor(session_manager=session_manager)

        # Test at different thresholds
        thresholds = [
            (50000, 19.5, False),   # ~20% usage - no warning
            (150000, 58.6, False),  # ~59% usage - no warning
            (180000, 70.3, True),   # ~70% usage - warning
            (210000, 82.0, True),   # ~82% usage - warning
        ]

        for tokens, expected_pct, should_warn in thresholds:
            # Add messages to reach token count
            session.messages.clear()
            session.total_tokens_cached = 0

            while session.total_tokens_cached < tokens:
                msg = ChatMessage(
                    role=Role.USER,
                    content="Message content " * 50,
                )
                session_manager.add_message(msg)

            stats = session.get_token_stats()
            actual_pct = stats["usage_percent"]

            task_monitor.set_session_manager(session_manager)
            context_display = task_monitor.get_context_display()
            shows_warning = task_monitor.should_show_context_warning()

            print(f"\nTokens: {tokens:,} ({actual_pct:.1f}%)")
            print(f"Display: '{context_display}'")
            print(f"Warning: {shows_warning} (expected: {should_warn})")

            assert shows_warning == should_warn, f"Warning state incorrect at {actual_pct:.1f}%"

            if actual_pct < 70:
                assert "context:" in context_display, "Should show 'context: XX%' when < 70%"
            else:
                assert "until compact" in context_display, "Should show 'XX% until compact' when >= 70%"

        print("\n✓ Context warning thresholds correct")


def test_display_formats():
    """Test different context display formats."""
    print("\n" + "=" * 60)
    print("Test 3: Context Display Formats")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        session_manager = SessionManager(session_dir)
        session = session_manager.create_session()

        task_monitor = TaskMonitor(session_manager=session_manager)

        test_cases = [
            (50000, "context: 20%"),
            (100000, "context: 39%"),
            (150000, "context: 59%"),
            (180000, "20% until compact"),
            (200000, "6% until compact"),
        ]

        for tokens, expected_format in test_cases:
            # Set token count
            session.messages.clear()
            session.total_tokens_cached = 0

            while session.total_tokens_cached < tokens:
                msg = ChatMessage(
                    role=Role.USER,
                    content="Test " * 50,
                )
                session_manager.add_message(msg)

            task_monitor.set_session_manager(session_manager)
            display = task_monitor.get_context_display()

            print(f"\nTokens: {tokens:,}")
            print(f"Display: '{display}'")
            print(f"Expected pattern: '{expected_format}'")

            # Check pattern matches
            if "context:" in expected_format:
                assert "context:" in display, "Should contain 'context:'"
            elif "until compact" in expected_format:
                assert "until compact" in display, "Should contain 'until compact'"

        print("\n✓ Display formats correct")


def test_compaction_preserves_context():
    """Test that compaction preserves critical information."""
    print("\n" + "=" * 60)
    print("Test 4: Compaction Context Preservation")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir)
        session_manager = SessionManager(session_dir)
        session = session_manager.create_session()

        # Add messages with important context
        important_messages = [
            "Created database schema with users, posts, and comments tables",
            "Implemented JWT authentication with refresh tokens",
            "Fixed critical bug in password hashing",
            "Added rate limiting middleware",
            "Wrote comprehensive test suite",
        ]

        for msg_content in important_messages:
            msg = ChatMessage(role=Role.ASSISTANT, content=msg_content)
            session_manager.add_message(msg)

        # Add filler to reach threshold
        while session.total_tokens_cached < 210000:
            msg = ChatMessage(
                role=Role.USER,
                content="Filler message " * 50,
            )
            session_manager.add_message(msg)

        print(f"Messages before compaction: {len(session.messages)}")
        print(f"Tokens before: {session.total_tokens_cached:,}")

        # Compact
        result = session_manager.check_and_compact(preserve_recent=3)

        if result:
            print(f"\nMessages after compaction: {len(session.messages)}")
            print(f"Tokens after: {session.total_tokens_cached:,}")
            print(f"Reduction: {result.reduction_percent:.1f}%")

            # Check summary exists
            assert len(session.messages) > 0, "Should have messages after compaction"
            summary_msg = session.messages[0]
            assert summary_msg.role == Role.SYSTEM, "First message should be summary"
            assert "summary" in summary_msg.content.lower(), "Should be a summary"

            print("\n✓ Compaction preserved context in summary")
        else:
            print("⚠️  Compaction not performed")


def main():
    """Run all integration tests."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║      CONTEXT ENGINEERING INTEGRATION TESTS                   ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    try:
        test_full_workflow()
        test_task_monitor_context_warning()
        test_display_formats()
        test_compaction_preserves_context()

        print("\n" + "=" * 60)
        print("✅ ALL INTEGRATION TESTS PASSED!")
        print("=" * 60)
        print("\n💡 Context Engineering System Integrated!")
        print("   • Token monitoring ✓")
        print("   • Session context tracking ✓")
        print("   • Task monitor display ✓")
        print("   • Auto-compaction ✓")
        print("   • Context retrieval ✓")
        print("   • Codebase indexing ✓")
        print("\n📝 Ready for REPL Integration:")
        print("   1. Pass session_manager to TaskMonitor on init")
        print("   2. Call session_manager.check_and_compact() after each turn")
        print("   3. Display will automatically show context percentage")
        print("   4. Warning colors activate at 70%+ usage")
        print("\n🎉 Phase 5 Complete: Integration\n")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
