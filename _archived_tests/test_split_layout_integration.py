#!/usr/bin/env python3
"""Test split layout integration in REPL."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from swecli.core.management import ConfigManager
from swecli.core.management import SessionManager
from swecli.repl.repl import REPL
from swecli.models.config import AppConfig


def test_split_layout_disabled():
    """Test REPL with split layout DISABLED (default behavior)."""
    print("Testing REPL with split layout DISABLED...")

    config_manager = ConfigManager()
    config = config_manager.get_config()

    # Verify flag is False by default
    assert not config.use_split_layout, "use_split_layout should be False by default"
    print("✓ Config flag is False by default")

    # Initialize session manager
    session_dir = Path(config.session_dir).expanduser()
    session_manager = SessionManager(session_dir)
    session_manager.create_session(working_directory=str(Path.cwd()))

    # Create REPL
    repl = REPL(config_manager, session_manager)

    # Verify split layout is NOT created
    assert repl._split_layout is None, "Split layout should be None when disabled"
    print("✓ Split layout is not created when disabled")

    # Verify console is DualConsole
    from swecli.ui.dual_console import DualConsole
    assert isinstance(repl.console, DualConsole), "Console should be DualConsole"
    print("✓ Console is DualConsole")

    # Verify buffer exists
    assert repl._conversation_buffer is not None, "Conversation buffer should exist"
    print("✓ Conversation buffer exists")

    print("\n✅ DISABLED mode works correctly!\n")
    return True


def test_split_layout_enabled():
    """Test REPL with split layout ENABLED."""
    print("Testing REPL with split layout ENABLED...")

    # Create config with split layout enabled
    config = AppConfig(use_split_layout=True)

    # Manually create config manager and set the config
    config_manager = ConfigManager()
    config_manager._config = config  # Override config

    # Verify flag is True
    assert config.use_split_layout, "use_split_layout should be True"
    print("✓ Config flag is True")

    # Initialize session manager
    session_dir = Path(config.session_dir).expanduser()
    session_manager = SessionManager(session_dir)
    session_manager.create_session(working_directory=str(Path.cwd()))

    # Create REPL
    repl = REPL(config_manager, session_manager)

    # Verify split layout IS created
    assert repl._split_layout is not None, "Split layout should be created when enabled"
    print("✓ Split layout is created when enabled")

    # Verify it's the right type
    from swecli.ui.split_layout import SplitScreenLayout
    assert isinstance(repl._split_layout, SplitScreenLayout), "Should be SplitScreenLayout instance"
    print("✓ Split layout is correct type")

    # Verify it uses the conversation buffer
    assert repl._split_layout.buffer is repl._conversation_buffer, "Split layout should use REPL's buffer"
    print("✓ Split layout uses conversation buffer")

    # Verify console is still DualConsole
    from swecli.ui.dual_console import DualConsole
    assert isinstance(repl.console, DualConsole), "Console should be DualConsole"
    print("✓ Console is DualConsole")

    print("\n✅ ENABLED mode works correctly!\n")
    return True


if __name__ == "__main__":
    try:
        success_disabled = test_split_layout_disabled()
        success_enabled = test_split_layout_enabled()

        if success_disabled and success_enabled:
            print("=" * 60)
            print("✅ ALL TESTS PASSED!")
            print("=" * 60)
            print("\nBoth modes work correctly:")
            print("  • DISABLED (default): Uses traditional output")
            print("  • ENABLED: Creates split layout structure")
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
