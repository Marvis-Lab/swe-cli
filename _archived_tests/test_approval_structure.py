"""Test approval menu structure without interaction."""

from rich.console import Console

from swecli.core.approval import ApprovalManager, ApprovalChoice
from swecli.models.operation import Operation, OperationType

def test_approval_structure():
    """Test the approval menu structure and methods."""
    console = Console()
    approval_manager = ApprovalManager(console)

    print("\n═══════════════════════════════════════════════")
    print("  SWE-CLI Approval Structure Test")
    print("═══════════════════════════════════════════════\n")

    # Test 1: Verify ApprovalChoice enum values
    print("Test 1: ApprovalChoice enum values")
    assert ApprovalChoice.APPROVE == "1", "APPROVE should be '1'"
    assert ApprovalChoice.APPROVE_ALL == "2", "APPROVE_ALL should be '2'"
    assert ApprovalChoice.DENY == "3", "DENY should be '3'"
    print("✓ Enum values correct\n")

    # Test 2: Test message generation
    print("Test 2: Conversational message generation")

    # File write
    op_write = Operation(
        type=OperationType.FILE_WRITE,
        target="test.py",
        parameters={"content": "code"},
    )
    msg_write = approval_manager._create_operation_message(op_write, "preview")
    print(f"  File write: {msg_write}")
    assert "create/write" in msg_write.lower(), "Message should mention create/write"

    # File edit
    op_edit = Operation(
        type=OperationType.FILE_EDIT,
        target="test.py",
        parameters={"content": "new code"},
    )
    msg_edit = approval_manager._create_operation_message(op_edit, "preview")
    print(f"  File edit: {msg_edit}")
    assert "edit" in msg_edit.lower(), "Message should mention edit"

    # Bash execute
    op_bash = Operation(
        type=OperationType.BASH_EXECUTE,
        target="ls -la",
    )
    msg_bash = approval_manager._create_operation_message(op_bash, "preview")
    print(f"  Bash: {msg_bash}")
    assert "run" in msg_bash.lower() or "command" in msg_bash.lower(), "Message should mention run/command"

    print("✓ All messages are conversational\n")

    # Test 3: Auto-approve functionality
    print("Test 3: Auto-approve functionality")
    approval_manager.auto_approve_remaining = True
    result = approval_manager.request_approval(op_write, "preview")
    assert result.approved, "Should be auto-approved"
    assert result.apply_to_all, "Should have apply_to_all set"
    print("✓ Auto-approve works correctly\n")

    # Test 4: Reset auto-approve
    print("Test 4: Reset auto-approve")
    approval_manager.reset_auto_approve()
    assert not approval_manager.auto_approve_remaining, "Should be reset"
    print("✓ Reset works correctly\n")

    print("✅ All structure tests passed!\n")
    print("Note: Interactive menu testing requires manual testing.")
    print("Run 'python test_approval_menu.py' for interactive tests.\n")

    return True

if __name__ == "__main__":
    try:
        success = test_approval_structure()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
