"""Tests for ConfigCommands._switch_to_model (swecli/repl/commands/config_commands.py)."""

from unittest.mock import MagicMock, patch

import pytest

from swecli.config.models import ModelInfo, ModelRegistry, ProviderInfo
from swecli.models.config import AppConfig
from swecli.repl.commands.config_commands import ConfigCommands


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_model_info(
    model_id="test-model",
    name="Test Model",
    provider="Test",
    context_length=128000,
    capabilities=None,
    supports_temperature=True,
    recommended=False,
):
    return ModelInfo(
        id=model_id,
        name=name,
        provider=provider,
        context_length=context_length,
        capabilities=capabilities or ["text"],
        supports_temperature=supports_temperature,
        recommended=recommended,
    )


def _make_provider_info(provider_id="openai", name="OpenAI"):
    return ProviderInfo(
        id=provider_id,
        name=name,
        description="Test provider",
        api_key_env=f"{provider_id.upper()}_API_KEY",
        api_base_url=f"https://api.{provider_id}.com",
        models={},
    )


@pytest.fixture
def config():
    return AppConfig(
        model_provider="fireworks",
        model="accounts/fireworks/models/some-model",
    )


@pytest.fixture
def config_manager(config):
    cm = MagicMock()
    cm.get_config.return_value = config
    cm.save_config = MagicMock()
    return cm


@pytest.fixture
def console():
    return MagicMock()


@pytest.fixture
def commands(console, config_manager):
    return ConfigCommands(console=console, config_manager=config_manager)


# ---------------------------------------------------------------------------
# Tests: _switch_to_model
# ---------------------------------------------------------------------------

class TestSwitchToModel:
    """Test the _switch_to_model method."""

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_switch_normal_model(self, mock_get_registry, commands, config_manager, config):
        """Switching normal model should update provider and model."""
        model = _make_model_info("gpt-4o", "GPT-4o", "OpenAI", 128000, ["text", "vision"])
        provider = _make_provider_info("openai", "OpenAI")

        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-4o", model)
        mock_registry.get_provider.return_value = provider
        mock_get_registry.return_value = mock_registry

        result = commands._switch_to_model("openai", "gpt-4o", "normal")

        assert result.success is True
        assert config.model_provider == "openai"
        assert config.model == "gpt-4o"
        config_manager.save_config.assert_called_once()

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_switch_normal_recalculates_context(self, mock_get_registry, commands, config):
        """Switching normal model should recalculate max_context_tokens."""
        model = _make_model_info("gpt-4o", context_length=128000)

        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-4o", model)
        mock_registry.get_provider.return_value = _make_provider_info()
        mock_get_registry.return_value = mock_registry

        commands._switch_to_model("openai", "gpt-4o", "normal")

        assert config.max_context_tokens == int(128000 * 0.8)

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_switch_thinking_model(self, mock_get_registry, commands, config):
        """Switching thinking model should only update thinking fields."""
        model = _make_model_info("o3", "O3", "OpenAI", 200000, ["text", "reasoning"])

        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "o3", model)
        mock_registry.get_provider.return_value = _make_provider_info()
        mock_get_registry.return_value = mock_registry

        result = commands._switch_to_model("openai", "o3", "thinking")

        assert result.success is True
        assert config.model_thinking_provider == "openai"
        assert config.model_thinking == "o3"
        # Normal model should be unchanged
        assert config.model_provider == "fireworks"

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_switch_vlm_model(self, mock_get_registry, commands, config):
        """Switching VLM model should only update VLM fields."""
        model = _make_model_info("gpt-4o", "GPT-4o", "OpenAI", 128000, ["text", "vision"])

        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-4o", model)
        mock_registry.get_provider.return_value = _make_provider_info()
        mock_get_registry.return_value = mock_registry

        result = commands._switch_to_model("openai", "gpt-4o", "vlm")

        assert result.success is True
        assert config.model_vlm_provider == "openai"
        assert config.model_vlm == "gpt-4o"
        # Normal model should be unchanged
        assert config.model_provider == "fireworks"

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_model_not_found(self, mock_get_registry, commands):
        """Should return failure when model not found in registry."""
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = None
        mock_get_registry.return_value = mock_registry

        result = commands._switch_to_model("openai", "nonexistent", "normal")

        assert result.success is False
        assert "not found" in result.message.lower()

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_provider_mismatch(self, mock_get_registry, commands):
        """Should return failure when provider doesn't match."""
        model = _make_model_info("gpt-4o")

        mock_registry = MagicMock()
        # Model found under openai, but we pass fireworks
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-4o", model)
        mock_get_registry.return_value = mock_registry

        result = commands._switch_to_model("fireworks", "gpt-4o", "normal")

        assert result.success is False
        assert "mismatch" in result.message.lower()

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_save_failure(self, mock_get_registry, commands, config_manager):
        """Should return failure when config save raises."""
        model = _make_model_info("gpt-4o")

        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-4o", model)
        mock_registry.get_provider.return_value = _make_provider_info()
        mock_get_registry.return_value = mock_registry

        config_manager.save_config.side_effect = IOError("Disk full")

        result = commands._switch_to_model("openai", "gpt-4o", "normal")

        assert result.success is False

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_result_data_contains_model_info(self, mock_get_registry, commands):
        """Successful result should include model info and provider in data."""
        model = _make_model_info("gpt-4o", "GPT-4o")

        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-4o", model)
        mock_registry.get_provider.return_value = _make_provider_info()
        mock_get_registry.return_value = mock_registry

        result = commands._switch_to_model("openai", "gpt-4o", "normal")

        assert result.data is not None
        assert result.data["model"] is model
        assert result.data["provider"] == "openai"
        assert result.data["mode"] == "normal"


class TestAutoPopulateSlots:
    """Test auto-population of thinking/vision slots when setting normal model."""

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_auto_populate_thinking_from_reasoning(self, mock_get_registry, commands, config):
        """Normal model with reasoning capability should auto-set thinking slot."""
        model = _make_model_info(
            "gpt-5", "GPT-5", "OpenAI", 128000, ["text", "vision", "reasoning"]
        )

        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-5", model)
        mock_registry.get_provider.return_value = _make_provider_info()
        mock_get_registry.return_value = mock_registry

        # Ensure thinking slot is not set
        assert config.model_thinking is None

        commands._switch_to_model("openai", "gpt-5", "normal")

        assert config.model_thinking == "gpt-5"
        assert config.model_thinking_provider == "openai"

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_auto_populate_vision_from_vision_cap(self, mock_get_registry, commands, config):
        """Normal model with vision capability should auto-set vision slot."""
        model = _make_model_info("gpt-4o", "GPT-4o", "OpenAI", 128000, ["text", "vision"])

        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-4o", model)
        mock_registry.get_provider.return_value = _make_provider_info()
        mock_get_registry.return_value = mock_registry

        assert config.model_vlm is None

        commands._switch_to_model("openai", "gpt-4o", "normal")

        assert config.model_vlm == "gpt-4o"
        assert config.model_vlm_provider == "openai"

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_no_auto_populate_when_already_set(self, mock_get_registry, commands, config):
        """Should not overwrite existing thinking/vision slot."""
        config.model_thinking = "o3"
        config.model_thinking_provider = "openai"
        config.model_vlm = "gpt-4o"
        config.model_vlm_provider = "openai"

        model = _make_model_info(
            "gpt-5", "GPT-5", "OpenAI", 128000, ["text", "vision", "reasoning"]
        )

        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-5", model)
        mock_registry.get_provider.return_value = _make_provider_info()
        mock_get_registry.return_value = mock_registry

        commands._switch_to_model("openai", "gpt-5", "normal")

        # Should remain unchanged
        assert config.model_thinking == "o3"
        assert config.model_vlm == "gpt-4o"

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_no_auto_populate_for_text_only(self, mock_get_registry, commands, config):
        """Text-only model should not auto-populate thinking/vision."""
        model = _make_model_info("gpt-3.5-turbo", "GPT-3.5", "OpenAI", 16000, ["text"])

        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-3.5-turbo", model)
        mock_registry.get_provider.return_value = _make_provider_info()
        mock_get_registry.return_value = mock_registry

        commands._switch_to_model("openai", "gpt-3.5-turbo", "normal")

        assert config.model_thinking is None
        assert config.model_vlm is None

    @patch("swecli.repl.commands.config_commands.get_model_registry")
    def test_no_auto_populate_on_thinking_mode(self, mock_get_registry, commands, config):
        """Setting thinking model should NOT auto-populate other slots."""
        model = _make_model_info(
            "o3", "O3", "OpenAI", 200000, ["text", "reasoning"]
        )

        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "o3", model)
        mock_registry.get_provider.return_value = _make_provider_info()
        mock_get_registry.return_value = mock_registry

        commands._switch_to_model("openai", "o3", "thinking")

        # VLM should not be auto-populated when switching thinking slot
        assert config.model_vlm is None
