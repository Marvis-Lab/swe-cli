"""Helpers for resolving API endpoints and headers."""

from __future__ import annotations

from typing import Tuple, Any

from swecli.models.config import AppConfig


# Models that require max_completion_tokens instead of max_tokens
_MAX_COMPLETION_TOKENS_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def uses_max_completion_tokens(model: str) -> bool:
    """Check if a model requires max_completion_tokens instead of max_tokens.

    GPT-5 and O-series models (o1, o3, o4) use max_completion_tokens parameter
    instead of max_tokens for the OpenAI API.

    Args:
        model: The model ID string

    Returns:
        True if the model uses max_completion_tokens
    """
    return model.startswith(_MAX_COMPLETION_TOKENS_PREFIXES)


def build_max_tokens_param(model: str, max_tokens: int) -> dict[str, int]:
    """Build the appropriate max tokens parameter for a model.

    Args:
        model: The model ID string
        max_tokens: The max tokens value

    Returns:
        Dict with either {"max_completion_tokens": value} or {"max_tokens": value}
    """
    if uses_max_completion_tokens(model):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


def resolve_api_config(config: AppConfig) -> Tuple[str, dict[str, str]]:
    """Return the API URL and headers according to the configured provider.

    Note: This is used for OpenAI-compatible providers (Fireworks, OpenAI).
    Anthropic uses a different client (AnthropicAdapter).
    """
    api_key = config.get_api_key()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    if config.model_provider == "fireworks":
        api_url = "https://api.fireworks.ai/inference/v1/chat/completions"
    elif config.model_provider == "openai":
        api_url = "https://api.openai.com/v1/chat/completions"
    elif config.model_provider == "anthropic":
        # Anthropic will use AnthropicAdapter, but provide URL for reference
        api_url = "https://api.anthropic.com/v1/messages"
    else:
        api_url = f"{config.api_base_url}/chat/completions"

    return api_url, headers


def create_http_client(config: AppConfig) -> Any:
    """Create the appropriate HTTP client based on the provider.

    Returns:
        AgentHttpClient for OpenAI-compatible APIs (Fireworks, OpenAI)
        AnthropicAdapter for Anthropic
    """
    if config.model_provider == "anthropic":
        from .anthropic_adapter import AnthropicAdapter
        api_key = config.get_api_key()
        return AnthropicAdapter(api_key)
    else:
        from .http_client import AgentHttpClient
        api_url, headers = resolve_api_config(config)
        return AgentHttpClient(api_url, headers)
