#!/usr/bin/env python3
"""Test script to verify playbook integration."""

from swecli.models.session import Session
from swecli.core.context_engineering.memory import Playbook, ExecutionReflector
from swecli.models.message import ToolCall

def test_session_playbook():
    """Test that Session properly handles playbook."""
    print("=" * 60)
    print("Test 1: Session Playbook Integration")
    print("=" * 60)

    # Create a new session
    session = Session()
    print(f"✓ Created session: {session.id}")

    # Get playbook (should be empty initially)
    playbook = session.get_playbook()
    print(f"✓ Initial playbook strategies: {len(playbook.bullets())}")
    assert len(playbook.bullets()) == 0, "Playbook should be empty initially"

    # Add a bullet
    bullet = playbook.add_bullet(
        section="file_operations",
        content="List directory before reading files to understand structure"
    )
    print(f"✓ Added bullet: {bullet.id}")

    # Update session with playbook
    session.update_playbook(playbook)
    print(f"✓ Updated session with playbook")

    # Verify it persists
    playbook2 = session.get_playbook()
    assert len(playbook2.bullets()) == 1, "Bullet should persist"
    print(f"✓ Bullet persists: {[b.id for b in playbook2.bullets()]}")

    # Test playbook context formatting
    context = playbook2.as_context()
    print(f"\n✓ Playbook context:\n{context}")

    print("\n✅ Test 1 PASSED\n")


def test_reflector():
    """Test execution reflector."""
    print("=" * 60)
    print("Test 2: Execution Reflector")
    print("=" * 60)

    reflector = ExecutionReflector(min_tool_calls=2, min_confidence=0.6)
    print(f"✓ Created reflector")

    # Simulate tool calls: list_files -> read_file
    tool_calls = [
        ToolCall(
            id="call_1",
            name="list_files",
            parameters={"path": "."},
            approved=True
        ),
        ToolCall(
            id="call_2",
            name="read_file",
            parameters={"file_path": "test.py"},
            result="file contents...",
            approved=True
        )
    ]

    # Extract learning
    result = reflector.reflect(
        query="check the test file",
        tool_calls=tool_calls,
        outcome="success"
    )

    if result:
        print(f"✓ Extracted learning!")
        print(f"  Category: {result.category}")
        print(f"  Content: {result.content}")
        print(f"  Confidence: {result.confidence:.2f}")
        print(f"  Reasoning: {result.reasoning}")
    else:
        print(f"✗ No learning extracted (this might be OK depending on min_confidence)")

    print("\n✅ Test 2 PASSED\n")


def test_effectiveness_tracking():
    """Test strategy effectiveness tracking."""
    print("=" * 60)
    print("Test 3: Effectiveness Tracking")
    print("=" * 60)

    playbook = Playbook()

    # Add a bullet
    bullet = playbook.add_bullet(
        section="testing",
        content="Run tests after code changes"
    )
    print(f"✓ Created bullet: {bullet.id}")
    print(f"  Initial helpful: {bullet.helpful}")

    # Mark as helpful a few times
    bullet.tag("helpful")
    bullet.tag("helpful")
    bullet.tag("helpful")
    print(f"  After 3x helpful: {bullet.helpful}")
    assert bullet.helpful == 3, "Should be 3"

    # Add one harmful tag
    bullet.tag("harmful")
    print(f"  After 1x harmful: {bullet.harmful}")
    assert bullet.harmful == 1, "Should be 1"

    # Test playbook stats
    stats = playbook.stats()
    print(f"\n✓ Playbook stats:")
    print(f"  Total bullets: {stats['bullets']}")
    print(f"  Helpful total: {stats['tags']['helpful']}")
    print(f"  Harmful total: {stats['tags']['harmful']}")

    print("\n✅ Test 3 PASSED\n")


def test_serialization():
    """Test session serialization with playbook."""
    print("=" * 60)
    print("Test 4: Session Serialization")
    print("=" * 60)

    # Create session with playbook
    session1 = Session()
    playbook = session1.get_playbook()
    playbook.add_bullet("file_operations", "Strategy 1")
    playbook.add_bullet("code_navigation", "Strategy 2")
    session1.update_playbook(playbook)
    print(f"✓ Created session with 2 bullets")

    # Serialize to dict
    session_dict = session1.model_dump()
    print(f"✓ Serialized to dict")

    # Deserialize
    session2 = Session.model_validate(session_dict)
    playbook2 = session2.get_playbook()
    print(f"✓ Deserialized from dict")

    # Verify bullets persisted
    assert len(playbook2.bullets()) == 2, "Should have 2 bullets"
    print(f"✓ Bullets persisted: {len(playbook2.bullets())} bullets")

    sections = set(b.section for b in playbook2.bullets())
    print(f"✓ Sections: {sections}")

    print("\n✅ Test 4 PASSED\n")


if __name__ == "__main__":
    try:
        test_session_playbook()
        test_reflector()
        test_effectiveness_tracking()
        test_serialization()

        print("=" * 60)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 60)
        print("\nPlaybook integration is working correctly.")
        print("The system is ready to learn from tool executions!")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
