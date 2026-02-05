"""Tests for model selection in AppConfig (swecli/models/config.py)."""

import os
from unittest.mock import patch, MagicMock

import pytest

from swecli.models.config import AppConfig


class TestAppConfigDefaults:
    """Test default model configuration values."""

    def test_default_provider(self):
        """Default provider should be fireworks."""
        config = AppConfig()
        assert config.model_provider == "fireworks"

    def test_default_model(self):
        """Default model should be set."""
        config = AppConfig()
        assert config.model == "accounts/fireworks/models/kimi-k2-instruct-0905"

    def test_default_thinking_model_is_none(self):
        """Thinking model should default to None."""
        config = AppConfig()
        assert config.model_thinking is None
        assert config.model_thinking_provider is None

    def test_default_vlm_model_is_none(self):
        """VLM model should default to None."""
        config = AppConfig()
        assert config.model_vlm is None
        assert config.model_vlm_provider is None


class TestProviderValidation:
    """Test model provider validation."""

    def test_valid_providers(self):
        """All supported providers should be accepted."""
        for provider in ["fireworks", "anthropic", "openai"]:
            config = AppConfig(model_provider=provider)
            assert config.model_provider == provider

    def test_invalid_provider_raises(self):
        """Unsupported providers should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported provider"):
            AppConfig(model_provider="invalid_provider")

    def test_invalid_provider_error_message(self):
        """Error message should list supported providers."""
        with pytest.raises(ValueError, match="fireworks.*anthropic.*openai"):
            AppConfig(model_provider="gemini")


class TestGetApiKey:
    """Test API key retrieval logic."""

    def test_api_key_from_config(self):
        """Should return API key from config if set."""
        config = AppConfig(api_key="test-key-123")
        assert config.get_api_key() == "test-key-123"

    @patch.dict(os.environ, {"FIREWORKS_API_KEY": "fw-key"})
    def test_api_key_from_env_fireworks(self):
        """Should get Fireworks API key from environment."""
        config = AppConfig(model_provider="fireworks")
        assert config.get_api_key() == "fw-key"

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ant-key"})
    def test_api_key_from_env_anthropic(self):
        """Should get Anthropic API key from environment."""
        config = AppConfig(model_provider="anthropic")
        assert config.get_api_key() == "ant-key"

    @patch.dict(os.environ, {"OPENAI_API_KEY": "oai-key"})
    def test_api_key_from_env_openai(self):
        """Should get OpenAI API key from environment."""
        config = AppConfig(model_provider="openai")
        assert config.get_api_key() == "oai-key"

    def test_missing_api_key_raises(self):
        """Should raise ValueError when no API key is available."""
        config = AppConfig(model_provider="openai")
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="No API key found"):
                config.get_api_key()

    def test_config_api_key_takes_precedence(self):
        """Config API key should take precedence over env var."""
        config = AppConfig(model_provider="openai", api_key="config-key")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}):
            assert config.get_api_key() == "config-key"


class TestGetModelInfo:
    """Test model info retrieval from registry."""

    @patch("swecli.config.get_model_registry")
    def test_get_model_info_found(self, mock_get_registry):
        """Should return ModelInfo when model exists in registry."""
        mock_model_info = MagicMock()
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-4o", mock_model_info)
        mock_get_registry.return_value = mock_registry

        config = AppConfig(model_provider="openai", model="gpt-4o")
        result = config.get_model_info()

        assert result is mock_model_info
        mock_registry.find_model_by_id.assert_called_once_with("gpt-4o")

    @patch("swecli.config.get_model_registry")
    def test_get_model_info_not_found(self, mock_get_registry):
        """Should return None when model not in registry."""
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = None
        mock_get_registry.return_value = mock_registry

        config = AppConfig(model_provider="openai", model="nonexistent-model")
        result = config.get_model_info()

        assert result is None


class TestGetThinkingModelInfo:
    """Test thinking model info retrieval with fallback logic."""

    @patch("swecli.config.get_model_registry")
    def test_thinking_model_configured(self, mock_get_registry):
        """Should return thinking model info when configured."""
        mock_result = ("openai", "o3", MagicMock())
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = mock_result
        mock_get_registry.return_value = mock_registry

        config = AppConfig(
            model_provider="fireworks",
            model="accounts/fireworks/models/some-model",
            model_thinking_provider="openai",
            model_thinking="o3",
        )
        result = config.get_thinking_model_info()

        assert result is mock_result
        mock_registry.find_model_by_id.assert_called_once_with("o3")

    @patch("swecli.config.get_model_registry")
    def test_thinking_model_fallback_to_normal(self, mock_get_registry):
        """Should fall back to normal model when thinking model is not set."""
        mock_result = ("fireworks", "some-model", MagicMock())
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = mock_result
        mock_get_registry.return_value = mock_registry

        config = AppConfig(
            model_provider="fireworks",
            model="accounts/fireworks/models/some-model",
        )
        result = config.get_thinking_model_info()

        assert result is mock_result
        mock_registry.find_model_by_id.assert_called_once_with(
            "accounts/fireworks/models/some-model"
        )

    @patch("swecli.config.get_model_registry")
    def test_thinking_model_fallback_when_provider_none(self, mock_get_registry):
        """Should fall back when thinking provider is None but model is set."""
        mock_result = ("fireworks", "some-model", MagicMock())
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = mock_result
        mock_get_registry.return_value = mock_registry

        config = AppConfig(
            model_provider="fireworks",
            model="accounts/fireworks/models/some-model",
            model_thinking="o3",
            model_thinking_provider=None,
        )
        result = config.get_thinking_model_info()

        # Falls back because provider is None
        mock_registry.find_model_by_id.assert_called_once_with(
            "accounts/fireworks/models/some-model"
        )

    @patch("swecli.config.get_model_registry")
    def test_thinking_model_fallback_when_not_found(self, mock_get_registry):
        """Should fall back to normal model when thinking model not found in registry."""
        normal_result = ("fireworks", "some-model", MagicMock())
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.side_effect = [None, normal_result]
        mock_get_registry.return_value = mock_registry

        config = AppConfig(
            model_provider="fireworks",
            model="accounts/fireworks/models/some-model",
            model_thinking_provider="openai",
            model_thinking="nonexistent",
        )
        result = config.get_thinking_model_info()

        assert result is normal_result
        assert mock_registry.find_model_by_id.call_count == 2


class TestGetVlmModelInfo:
    """Test VLM model info retrieval with fallback logic."""

    @patch("swecli.config.get_model_registry")
    def test_vlm_model_configured(self, mock_get_registry):
        """Should return VLM model info when configured."""
        mock_result = ("openai", "gpt-4o", MagicMock())
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = mock_result
        mock_get_registry.return_value = mock_registry

        config = AppConfig(
            model_provider="fireworks",
            model="accounts/fireworks/models/some-model",
            model_vlm_provider="openai",
            model_vlm="gpt-4o",
        )
        result = config.get_vlm_model_info()

        assert result is mock_result

    @patch("swecli.config.get_model_registry")
    def test_vlm_fallback_to_normal_with_vision(self, mock_get_registry):
        """Should fall back to normal model if it has vision capability."""
        mock_model_info = MagicMock()
        mock_model_info.capabilities = ["text", "vision"]
        normal_result = ("openai", "gpt-4o", mock_model_info)
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = normal_result
        mock_get_registry.return_value = mock_registry

        config = AppConfig(model_provider="openai", model="gpt-4o")
        result = config.get_vlm_model_info()

        assert result is normal_result

    @patch("swecli.config.get_model_registry")
    def test_vlm_returns_none_when_normal_has_no_vision(self, mock_get_registry):
        """Should return None when normal model has no vision capability."""
        mock_model_info = MagicMock()
        mock_model_info.capabilities = ["text"]
        normal_result = ("fireworks", "some-model", mock_model_info)
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = normal_result
        mock_get_registry.return_value = mock_registry

        config = AppConfig(
            model_provider="fireworks",
            model="accounts/fireworks/models/some-model",
        )
        result = config.get_vlm_model_info()

        assert result is None

    @patch("swecli.config.get_model_registry")
    def test_vlm_returns_none_when_no_model_found(self, mock_get_registry):
        """Should return None when no model found at all."""
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = None
        mock_get_registry.return_value = mock_registry

        config = AppConfig(
            model_provider="fireworks",
            model="accounts/fireworks/models/nonexistent",
        )
        result = config.get_vlm_model_info()

        assert result is None


class TestShouldUseProviderForAll:
    """Test universal provider detection."""

    def test_openai_is_universal(self):
        """OpenAI should be universal provider."""
        config = AppConfig(model_provider="openai")
        assert config.should_use_provider_for_all("openai") is True

    def test_anthropic_is_universal(self):
        """Anthropic should be universal provider."""
        config = AppConfig(model_provider="openai")
        assert config.should_use_provider_for_all("anthropic") is True

    def test_fireworks_is_not_universal(self):
        """Fireworks should not be universal provider."""
        config = AppConfig()
        assert config.should_use_provider_for_all("fireworks") is False

    def test_unknown_provider_is_not_universal(self):
        """Unknown providers should not be universal."""
        config = AppConfig()
        assert config.should_use_provider_for_all("some_other") is False


class TestThreeModelSlotConfiguration:
    """Test the three-model slot system configuration."""

    def test_all_three_slots_configured(self):
        """All three model slots can be configured independently."""
        config = AppConfig(
            model_provider="fireworks",
            model="accounts/fireworks/models/some-model",
            model_thinking_provider="openai",
            model_thinking="o3",
            model_vlm_provider="anthropic",
            model_vlm="claude-opus-4-5-20251101",
        )
        assert config.model_provider == "fireworks"
        assert config.model == "accounts/fireworks/models/some-model"
        assert config.model_thinking_provider == "openai"
        assert config.model_thinking == "o3"
        assert config.model_vlm_provider == "anthropic"
        assert config.model_vlm == "claude-opus-4-5-20251101"

    def test_mixed_providers(self):
        """Each slot can use a different provider."""
        config = AppConfig(
            model_provider="fireworks",
            model="accounts/fireworks/models/some-model",
            model_thinking_provider="openai",
            model_thinking="o3",
            model_vlm_provider="openai",
            model_vlm="gpt-4o",
        )
        assert config.model_provider == "fireworks"
        assert config.model_thinking_provider == "openai"
        assert config.model_vlm_provider == "openai"

    def test_same_model_in_all_slots(self):
        """Same model can be used in all three slots."""
        config = AppConfig(
            model_provider="openai",
            model="gpt-4o",
            model_thinking_provider="openai",
            model_thinking="gpt-4o",
            model_vlm_provider="openai",
            model_vlm="gpt-4o",
        )
        assert config.model == "gpt-4o"
        assert config.model_thinking == "gpt-4o"
        assert config.model_vlm == "gpt-4o"
