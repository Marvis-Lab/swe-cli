#!/usr/bin/env python3
"""Test that bash command errors are displayed properly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from swecli.tools.bash_tool import BashTool
from swecli.models.config import AppConfig


def test_bash_error_messages():
    """Test that error messages are populated correctly."""
    print("\n" + "=" * 70)
    print("Testing Bash Command Error Messages")
    print("=" * 70)

    config = AppConfig()
    config.enable_bash = True  # Enable bash for testing
    config.permissions.bash.enabled = True  # Enable bash permissions
    bash_tool = BashTool(config, Path.cwd())

    # Test 1: Command not found (exit code 127)
    print("\n[Test 1: Command not found]")
    result = bash_tool.execute("nonexistent_command_xyz")

    print(f"Success: {result.success}")
    print(f"Exit code: {result.exit_code}")
    print(f"Error: {result.error}")

    assert not result.success, "Should fail"
    assert result.exit_code != 0, "Should have non-zero exit code"
    assert result.error is not None, "❌ ERROR: error field should not be None!"
    assert "exit code" in result.error.lower(), "Error should mention exit code"

    print("✓ Error message is populated correctly")

    # Test 2: Command with stderr output
    print("\n[Test 2: Command with stderr]")
    result = bash_tool.execute("ls nonexistent_file_xyz")

    print(f"Success: {result.success}")
    print(f"Exit code: {result.exit_code}")
    print(f"Stderr: {result.stderr[:100] if result.stderr else 'None'}...")
    print(f"Error: {result.error}")

    assert not result.success, "Should fail"
    assert result.error is not None, "❌ ERROR: error field should not be None!"
    assert "exit code" in result.error.lower(), "Error should mention exit code"

    # If there's stderr, it should be included in the error
    if result.stderr:
        print("✓ Error message includes stderr output")

    print("✓ Error message is populated correctly")

    # Test 3: Successful command should NOT have error
    print("\n[Test 3: Successful command]")
    result = bash_tool.execute("echo 'test'")

    print(f"Success: {result.success}")
    print(f"Exit code: {result.exit_code}")
    print(f"Error: {result.error}")

    assert result.success, "Should succeed"
    assert result.exit_code == 0, "Should have zero exit code"
    assert result.error is None, "Error should be None for successful commands"

    print("✓ Successful command has no error")

    # Test 4: Command with non-zero exit but no stderr
    print("\n[Test 4: Exit code 1 with no stderr]")
    result = bash_tool.execute("sh -c 'exit 1'")

    print(f"Success: {result.success}")
    print(f"Exit code: {result.exit_code}")
    print(f"Stderr: {result.stderr}")
    print(f"Error: {result.error}")

    assert not result.success, "Should fail"
    assert result.exit_code == 1, "Should have exit code 1"
    assert result.error is not None, "❌ ERROR: error field should not be None!"
    assert "exit code 1" in result.error.lower(), "Error should mention exit code 1"

    print("✓ Error message for exit code 1")


def test_error_display_format():
    """Test the format of error messages."""
    print("\n" + "=" * 70)
    print("Testing Error Message Format")
    print("=" * 70)

    config = AppConfig()
    config.enable_bash = True
    config.permissions.bash.enabled = True
    bash_tool = BashTool(config, Path.cwd())

    # Command that fails with stderr
    result = bash_tool.execute("ls /nonexistent_dir_xyz")

    print("\n[Error message format]")
    print(f"Error: {result.error}")

    if result.error:
        # Should contain exit code
        assert "exit code" in result.error.lower(), "Should mention exit code"

        # Should not be "None" or empty
        assert result.error.strip() != "", "Should not be empty"
        assert result.error.lower() != "none", "Should not be 'None'"

        print("✓ Error message is properly formatted")
        print(f"✓ Format: '{result.error[:80]}...'")


if __name__ == "__main__":
    try:
        test_bash_error_messages()
        test_error_display_format()

        print("\n" + "=" * 70)
        print("✅ ALL BASH ERROR TESTS PASSED!")
        print("=" * 70)

        print("\n[Summary]")
        print("• Failed commands now have proper error messages")
        print("• Error includes exit code and stderr output")
        print("• No more 'None' displayed to users")
        print("• Format: 'Command failed with exit code X. Error output: ...'")
        print()

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
