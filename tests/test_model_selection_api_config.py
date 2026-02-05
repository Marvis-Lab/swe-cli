"""Tests for API configuration helpers (swecli/core/agents/components/api/configuration.py)."""

import os
from unittest.mock import patch, MagicMock

import pytest

from swecli.core.agents.components.api.configuration import (
    uses_max_completion_tokens,
    build_max_tokens_param,
    build_temperature_param,
    resolve_api_config,
    create_http_client,
    create_http_client_for_provider,
)
from swecli.models.config import AppConfig


# ---------------------------------------------------------------------------
# uses_max_completion_tokens
# ---------------------------------------------------------------------------

class TestUsesMaxCompletionTokens:
    """Test detection of models requiring max_completion_tokens."""

    @pytest.mark.parametrize("model", ["o1", "o1-pro", "o1-mini"])
    def test_o1_series(self, model):
        assert uses_max_completion_tokens(model) is True

    @pytest.mark.parametrize("model", ["o3", "o3-pro", "o3-mini", "o3-deep-research"])
    def test_o3_series(self, model):
        assert uses_max_completion_tokens(model) is True

    @pytest.mark.parametrize("model", ["o4-mini", "o4-mini-deep-research"])
    def test_o4_series(self, model):
        assert uses_max_completion_tokens(model) is True

    @pytest.mark.parametrize("model", ["gpt-5", "gpt-5.1", "gpt-5.2", "gpt-5-mini"])
    def test_gpt5_series(self, model):
        assert uses_max_completion_tokens(model) is True

    @pytest.mark.parametrize(
        "model",
        ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo-2024-04-09", "gpt-3.5-turbo", "claude-3-sonnet"],
    )
    def test_non_matching_models(self, model):
        assert uses_max_completion_tokens(model) is False

    def test_fireworks_model(self):
        assert uses_max_completion_tokens("accounts/fireworks/models/some-model") is False


# ---------------------------------------------------------------------------
# build_max_tokens_param
# ---------------------------------------------------------------------------

class TestBuildMaxTokensParam:
    """Test building the correct max tokens parameter."""

    def test_o_series_uses_max_completion_tokens(self):
        result = build_max_tokens_param("o3", 16384)
        assert result == {"max_completion_tokens": 16384}

    def test_gpt5_uses_max_completion_tokens(self):
        result = build_max_tokens_param("gpt-5", 16384)
        assert result == {"max_completion_tokens": 16384}

    def test_gpt4_uses_max_tokens(self):
        result = build_max_tokens_param("gpt-4o", 16384)
        assert result == {"max_tokens": 16384}

    def test_fireworks_model_uses_max_tokens(self):
        result = build_max_tokens_param("accounts/fireworks/models/foo", 8192)
        assert result == {"max_tokens": 8192}

    def test_arbitrary_value(self):
        result = build_max_tokens_param("gpt-4o", 4096)
        assert result == {"max_tokens": 4096}


# ---------------------------------------------------------------------------
# build_temperature_param
# ---------------------------------------------------------------------------

class TestBuildTemperatureParam:
    """Test temperature parameter building with registry lookup."""

    @patch("swecli.config.models.get_model_registry")
    def test_model_supports_temperature(self, mock_get_registry):
        mock_model_info = MagicMock()
        mock_model_info.supports_temperature = True
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "gpt-4o", mock_model_info)
        mock_get_registry.return_value = mock_registry

        result = build_temperature_param("gpt-4o", 0.7)
        assert result == {"temperature": 0.7}

    @patch("swecli.config.models.get_model_registry")
    def test_model_does_not_support_temperature(self, mock_get_registry):
        mock_model_info = MagicMock()
        mock_model_info.supports_temperature = False
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = ("openai", "o1", mock_model_info)
        mock_get_registry.return_value = mock_registry

        result = build_temperature_param("o1", 0.7)
        assert result == {}

    @patch("swecli.config.models.get_model_registry")
    def test_model_not_found_includes_temperature(self, mock_get_registry):
        """Unknown models should still get temperature (fallback behavior)."""
        mock_registry = MagicMock()
        mock_registry.find_model_by_id.return_value = None
        mock_get_registry.return_value = mock_registry

        result = build_temperature_param("unknown-model", 0.5)
        assert result == {"temperature": 0.5}


# ---------------------------------------------------------------------------
# resolve_api_config
# ---------------------------------------------------------------------------

class TestResolveApiConfig:
    """Test API URL and header resolution by provider."""

    @patch.dict(os.environ, {"FIREWORKS_API_KEY": "fw-test-key"})
    def test_fireworks_url(self):
        config = AppConfig(model_provider="fireworks")
        url, headers = resolve_api_config(config)
        assert url == "https://api.fireworks.ai/inference/v1/chat/completions"
        assert "Bearer fw-test-key" in headers["Authorization"]

    @patch.dict(os.environ, {"OPENAI_API_KEY": "oai-test-key"})
    def test_openai_url(self):
        config = AppConfig(model_provider="openai")
        url, headers = resolve_api_config(config)
        assert url == "https://api.openai.com/v1/chat/completions"
        assert "Bearer oai-test-key" in headers["Authorization"]

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ant-test-key"})
    def test_anthropic_url(self):
        config = AppConfig(model_provider="anthropic")
        url, headers = resolve_api_config(config)
        assert url == "https://api.anthropic.com/v1/messages"

    @patch.dict(os.environ, {"OPENAI_API_KEY": "key"})
    def test_headers_include_content_type(self):
        config = AppConfig(model_provider="openai")
        _, headers = resolve_api_config(config)
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# create_http_client
# ---------------------------------------------------------------------------

class TestCreateHttpClient:
    """Test HTTP client creation based on provider."""

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ant-key"})
    def test_anthropic_returns_adapter(self):
        config = AppConfig(model_provider="anthropic")
        client = create_http_client(config)
        from swecli.core.agents.components.api.anthropic_adapter import AnthropicAdapter
        assert isinstance(client, AnthropicAdapter)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "oai-key"})
    def test_openai_returns_http_client(self):
        config = AppConfig(model_provider="openai")
        client = create_http_client(config)
        from swecli.core.agents.components.api.http_client import AgentHttpClient
        assert isinstance(client, AgentHttpClient)

    @patch.dict(os.environ, {"FIREWORKS_API_KEY": "fw-key"})
    def test_fireworks_returns_http_client(self):
        config = AppConfig(model_provider="fireworks")
        client = create_http_client(config)
        from swecli.core.agents.components.api.http_client import AgentHttpClient
        assert isinstance(client, AgentHttpClient)


# ---------------------------------------------------------------------------
# create_http_client_for_provider
# ---------------------------------------------------------------------------

class TestCreateHttpClientForProvider:
    """Test provider-specific HTTP client creation for thinking model slot."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "oai-key"})
    def test_openai_provider(self):
        config = AppConfig(model_provider="fireworks")
        client = create_http_client_for_provider("openai", config)
        from swecli.core.agents.components.api.http_client import AgentHttpClient
        assert isinstance(client, AgentHttpClient)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ant-key"})
    def test_anthropic_provider(self):
        config = AppConfig(model_provider="fireworks")
        client = create_http_client_for_provider("anthropic", config)
        from swecli.core.agents.components.api.anthropic_adapter import AnthropicAdapter
        assert isinstance(client, AnthropicAdapter)

    @patch.dict(os.environ, {"FIREWORKS_API_KEY": "fw-key"})
    def test_fireworks_provider(self):
        config = AppConfig(model_provider="openai")
        client = create_http_client_for_provider("fireworks", config)
        from swecli.core.agents.components.api.http_client import AgentHttpClient
        assert isinstance(client, AgentHttpClient)

    def test_unknown_provider_raises(self):
        config = AppConfig(model_provider="openai")
        with pytest.raises(ValueError, match="Unknown provider"):
            create_http_client_for_provider("unknown_provider", config)

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_openai_key_raises(self):
        config = AppConfig(model_provider="fireworks")
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            create_http_client_for_provider("openai", config)

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_anthropic_key_raises(self):
        config = AppConfig(model_provider="fireworks")
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            create_http_client_for_provider("anthropic", config)

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_fireworks_key_raises(self):
        config = AppConfig(model_provider="openai")
        with pytest.raises(ValueError, match="FIREWORKS_API_KEY"):
            create_http_client_for_provider("fireworks", config)
