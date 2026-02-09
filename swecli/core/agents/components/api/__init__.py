"""API integration layer for OpenDev agents.

This subpackage contains HTTP client wrappers, API configuration utilities,
and provider-specific adapters (Anthropic, OpenAI, Fireworks).
"""

from .anthropic_adapter import AnthropicAdapter
from .configuration import (
    build_max_tokens_param,
    build_temperature_param,
    create_http_client,
    create_http_client_for_provider,
    resolve_api_config,
)
from .http_client import AgentHttpClient, HttpResult

__all__ = [
    "AgentHttpClient",
    "AnthropicAdapter",
    "HttpResult",
    "build_max_tokens_param",
    "build_temperature_param",
    "create_http_client",
    "create_http_client_for_provider",
    "resolve_api_config",
]
