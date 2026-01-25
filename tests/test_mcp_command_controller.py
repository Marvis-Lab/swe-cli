"""Tests for MCPCommandController."""
from unittest.mock import Mock, patch
import pytest

from swecli.ui_textual.controllers.mcp_command_controller import MCPCommandController

@pytest.fixture
def mock_app():
    app = Mock()
    app.conversation = Mock()
    # Mock loop for _run_on_ui
    app._loop = Mock()
    return app

@pytest.fixture
def mock_repl():
    repl = Mock()
    repl.mcp_manager = Mock()
    return repl

@pytest.fixture
def controller(mock_app, mock_repl):
    return MCPCommandController(mock_app, mock_repl)

def test_handle_connect_success(controller, mock_app, mock_repl):
    """Test successful MCP connection."""
    # Setup MCP manager mock
    mock_repl.mcp_manager.is_connected.return_value = False
    mock_repl.mcp_manager.connect_sync.return_value = True
    mock_repl.mcp_manager.get_server_tools.return_value = ["tool1", "tool2"]

    # Mock TextualUICallback to verify calls
    # Note: handle_connect does a local import, so we must patch where it's defined
    with patch("swecli.ui_textual.ui_callback.TextualUICallback") as MockCallback:
        mock_ui_callback = MockCallback.return_value

        controller.handle_connect("/mcp connect github")

        # Verify spinner started
        mock_ui_callback.on_progress_start.assert_called_with("MCP (github)")

        # Verify connection attempted
        mock_repl.mcp_manager.connect_sync.assert_called_with("github")

        # Verify success message
        mock_ui_callback.on_progress_complete.assert_called_with("Connected (2 tools)")

        # Verify runtime tooling refresh
        mock_repl._refresh_runtime_tooling.assert_called_once()

def test_handle_connect_failure(controller, mock_app, mock_repl):
    """Test failed MCP connection."""
    # Setup failure
    mock_repl.mcp_manager.is_connected.return_value = False
    mock_repl.mcp_manager.connect_sync.return_value = False

    with patch("swecli.ui_textual.ui_callback.TextualUICallback") as MockCallback:
        mock_ui_callback = MockCallback.return_value

        controller.handle_connect("/mcp connect github")

        # Verify error message
        mock_ui_callback.on_progress_complete.assert_called_with("Connection failed", success=False)

        # Verify runtime tooling NOT refreshed
        mock_repl._refresh_runtime_tooling.assert_not_called()

def test_handle_connect_already_connected(controller, mock_app, mock_repl):
    """Test connecting to already connected server."""
    mock_repl.mcp_manager.is_connected.return_value = True
    mock_repl.mcp_manager.get_server_tools.return_value = ["tool1"]

    with patch("swecli.ui_textual.ui_callback.TextualUICallback") as MockCallback:
        mock_ui_callback = MockCallback.return_value

        controller.handle_connect("/mcp connect github")

        # Should not attempt connection
        mock_repl.mcp_manager.connect_sync.assert_not_called()

        # Should show already connected message
        mock_ui_callback.on_progress_complete.assert_called_with("Already connected (1 tools)")

def test_handle_connect_invalid_command(controller, mock_app):
    """Test invalid command format."""
    controller.handle_connect("/mcp connect") # Missing server name

    mock_app.conversation.add_error.assert_called_with("Usage: /mcp connect <server_name>")

def test_handle_connect_no_manager(controller, mock_app, mock_repl):
    """Test when MCP manager is missing."""
    mock_repl.mcp_manager = None

    controller.handle_connect("/mcp connect github")

    mock_app.conversation.add_error.assert_called_with("MCP manager not available")
