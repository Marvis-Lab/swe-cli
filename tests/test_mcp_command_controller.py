"""Tests for MCPCommandController."""
from unittest.mock import Mock, patch, MagicMock
import pytest

from swecli.ui_textual.controllers.mcp_command_controller import MCPCommandController

@pytest.fixture
def mock_app():
    app = Mock()
    app.conversation = Mock()
    # Mock loop for _run_on_ui
    app._loop = Mock()
    # Mock spinner service
    app.spinner_service = Mock()
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

    # Setup spinner mock
    mock_app.spinner_service.start.return_value = "spinner-id"

    controller.handle_connect("/mcp connect github")

    # Verify spinner started
    mock_app.spinner_service.start.assert_called_with("MCP (github)")

    # Verify connection attempted (might be in thread)
    # Since it's threaded, we might not see the call immediately unless we join or wait
    # Or if the thread runs instantly/is mocked.
    # The current implementation uses threading.Thread.
    # We can mock threading.Thread to run synchronously for tests.

    # Wait for thread to finish (it's daemon so join is tricky without reference)
    # But threading.Thread is standard library.
    # Let's assume the previous test worked because TextualUICallback was used differently?
    # No, the previous test code was mocking TextualUICallback which was NOT used in handle_connect for spinner anymore.
    # It uses spinner_service now.

    # We need to ensure the thread runs.
    # Patch threading.Thread to run target immediately
    with patch("threading.Thread") as MockThread:
        def side_effect(target=None, daemon=None):
            target() # Run immediately
            return MagicMock()
        MockThread.side_effect = side_effect

        controller.handle_connect("/mcp connect github")

        mock_repl.mcp_manager.connect_sync.assert_called_with("github")

        # Verify success message
        mock_app.spinner_service.stop.assert_called_with(
            "spinner-id", success=True, result_message="Connected (2 tools)"
        )

        # Verify runtime tooling refresh
        mock_repl._refresh_runtime_tooling.assert_called_once()

def test_handle_connect_failure(controller, mock_app, mock_repl):
    """Test failed MCP connection."""
    # Setup failure
    mock_repl.mcp_manager.is_connected.return_value = False
    mock_repl.mcp_manager.connect_sync.return_value = False
    mock_app.spinner_service.start.return_value = "spinner-id"

    with patch("threading.Thread") as MockThread:
        def side_effect(target=None, daemon=None):
            target()
            return MagicMock()
        MockThread.side_effect = side_effect

        controller.handle_connect("/mcp connect github")

        # Verify error message
        mock_app.spinner_service.stop.assert_called_with(
            "spinner-id", success=False, result_message="Connection failed"
        )

        # Verify runtime tooling NOT refreshed
        mock_repl._refresh_runtime_tooling.assert_not_called()

def test_handle_connect_already_connected(controller, mock_app, mock_repl):
    """Test connecting to already connected server."""
    mock_repl.mcp_manager.is_connected.return_value = True
    mock_repl.mcp_manager.get_server_tools.return_value = ["tool1"]
    mock_app.spinner_service.start.return_value = "spinner-id"

    controller.handle_connect("/mcp connect github")

    # Should not attempt connection
    mock_repl.mcp_manager.connect_sync.assert_not_called()

    # Should show already connected message
    mock_app.spinner_service.stop.assert_called_with(
        "spinner-id", success=True, result_message="Already connected (1 tools)"
    )

def test_handle_connect_invalid_command(controller, mock_app):
    """Test invalid command format."""
    controller.handle_connect("/mcp connect") # Missing server name

    mock_app.conversation.add_error.assert_called_with("Usage: /mcp connect <server_name>")

def test_handle_connect_no_manager(controller, mock_app, mock_repl):
    """Test when MCP manager is missing."""
    mock_repl.mcp_manager = None

    controller.handle_connect("/mcp connect github")

    mock_app.conversation.add_error.assert_called_with("MCP manager not available")
