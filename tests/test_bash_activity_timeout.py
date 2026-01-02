"""Tests for activity-based timeout in BashTool."""

import time
from pathlib import Path

import pytest

from swecli.core.context_engineering.tools.implementations.bash_tool import (
    BashTool,
    IDLE_TIMEOUT,
    MAX_TIMEOUT,
)
from swecli.models.config import AppConfig


@pytest.fixture
def bash_tool():
    """Create a BashTool instance for testing."""
    config = AppConfig()
    return BashTool(config, Path.cwd())


class TestActivityBasedTimeout:
    """Test activity-based timeout behavior."""

    def test_command_with_continuous_output_succeeds(self, bash_tool):
        """Commands that produce continuous output should not timeout."""
        # Output every 2 seconds for 10 seconds (well under IDLE_TIMEOUT)
        result = bash_tool.execute(
            'python -c "import time; [print(i, flush=True) or time.sleep(2) for i in range(5)]"'
        )
        assert result.success, f"Should succeed: {result.error}"
        assert "0" in result.stdout
        assert "4" in result.stdout

    def test_command_with_intermittent_output_succeeds(self, bash_tool):
        """Commands with output gaps under IDLE_TIMEOUT should succeed."""
        # Output every 10 seconds (under 60s IDLE_TIMEOUT)
        result = bash_tool.execute(
            'python -c "import time; [print(i, flush=True) or time.sleep(10) for i in range(3)]"'
        )
        assert result.success, f"Should succeed: {result.error}"

    def test_idle_command_times_out(self, bash_tool):
        """Commands with no output should timeout after IDLE_TIMEOUT."""
        # Temporarily reduce IDLE_TIMEOUT for faster testing
        import swecli.core.context_engineering.tools.implementations.bash_tool as bt
        original_idle = bt.IDLE_TIMEOUT
        bt.IDLE_TIMEOUT = 3  # 3 seconds for testing

        try:
            result = bash_tool.execute("sleep 10")  # 10 seconds, no output
            assert not result.success, "Should timeout"
            assert "no output" in result.error.lower(), f"Error: {result.error}"
        finally:
            bt.IDLE_TIMEOUT = original_idle

    def test_quick_command_succeeds(self, bash_tool):
        """Quick commands that complete before timeout should succeed."""
        result = bash_tool.execute('echo "hello world"')
        assert result.success
        assert "hello world" in result.stdout

    def test_error_message_includes_idle_time(self, bash_tool):
        """Timeout error message should mention no output."""
        import swecli.core.context_engineering.tools.implementations.bash_tool as bt
        original_idle = bt.IDLE_TIMEOUT
        bt.IDLE_TIMEOUT = 2  # 2 seconds for testing

        try:
            result = bash_tool.execute("sleep 5")
            assert not result.success
            assert "seconds of no output" in result.error
        finally:
            bt.IDLE_TIMEOUT = original_idle

    def test_activity_resets_idle_timer(self, bash_tool):
        """Each output line should reset the idle timer."""
        # Reduced idle timeout for faster testing
        import swecli.core.context_engineering.tools.implementations.bash_tool as bt
        original_idle = bt.IDLE_TIMEOUT
        bt.IDLE_TIMEOUT = 5  # 5 second idle timeout

        try:
            # Total time: 12 seconds, but gaps are only 3 seconds each
            # Should NOT timeout because each gap is under 5 seconds
            result = bash_tool.execute(
                'python -c "import time; [print(i, flush=True) or time.sleep(3) for i in range(4)]"'
            )
            assert result.success, f"Should succeed with intermittent output: {result.error}"
        finally:
            bt.IDLE_TIMEOUT = original_idle


class TestMaxTimeout:
    """Test absolute maximum timeout behavior."""

    def test_max_timeout_enforced(self, bash_tool):
        """Commands exceeding MAX_TIMEOUT should fail even with output."""
        import swecli.core.context_engineering.tools.implementations.bash_tool as bt
        original_max = bt.MAX_TIMEOUT
        bt.MAX_TIMEOUT = 5  # 5 seconds max for testing

        try:
            # Continuous output every second - would never hit idle timeout
            # But should hit max timeout at 5 seconds
            result = bash_tool.execute(
                'python -c "import time; [print(i, flush=True) or time.sleep(1) for i in range(100)]"'
            )
            assert not result.success, "Should hit max timeout"
            assert "maximum runtime" in result.error.lower(), f"Error: {result.error}"
        finally:
            bt.MAX_TIMEOUT = original_max


class TestOutputCallback:
    """Test that output callback works with activity-based timeout."""

    def test_callback_receives_output(self, bash_tool):
        """Output callback should receive all lines."""
        received_lines = []

        def callback(line, is_stderr=False):
            received_lines.append((line, is_stderr))

        result = bash_tool.execute(
            "python -c \"import sys; print('stdout'); print('stderr', file=sys.stderr)\"",
            output_callback=callback,
        )

        assert result.success
        stdout_lines = [line for line, is_err in received_lines if not is_err]
        stderr_lines = [line for line, is_err in received_lines if is_err]
        assert any("stdout" in line for line in stdout_lines)
        assert any("stderr" in line for line in stderr_lines)

    def test_activity_detected_without_callback(self, bash_tool):
        """Activity should be detected even without output callback."""
        import swecli.core.context_engineering.tools.implementations.bash_tool as bt
        original_idle = bt.IDLE_TIMEOUT
        bt.IDLE_TIMEOUT = 5

        try:
            # No callback, but should still detect activity
            result = bash_tool.execute(
                'python -c "import time; [print(i, flush=True) or time.sleep(2) for i in range(4)]"',
                output_callback=None,  # No callback
            )
            assert result.success, f"Should succeed: {result.error}"
        finally:
            bt.IDLE_TIMEOUT = original_idle
