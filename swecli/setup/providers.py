"""Provider definitions and model configurations using model registry."""

from typing import Dict, List, Any, Optional

from swecli.config import get_model_registry


def get_provider_config(provider_id: str) -> Optional[Dict[str, Any]]:
    """Get configuration for a specific provider from registry."""
    registry = get_model_registry()
    provider_info = registry.get_provider(provider_id)

    if not provider_info:
        return None

    return {
        "name": provider_info.name,
        "description": provider_info.description,
        "env_var": provider_info.api_key_env,
        "api_url": provider_info.api_base_url,
        "api_format": "openai" if provider_id != "anthropic" else "anthropic",
    }


def get_provider_models(provider_id: str) -> List[Dict[str, str]]:
    """Get available models for a provider from registry."""
    registry = get_model_registry()
    provider_info = registry.get_provider(provider_id)

    if not provider_info:
        return []

    # Convert ModelInfo objects to dict format for wizard
    models = []
    for model_info in provider_info.list_models():
        # Create description with pricing and context info
        description = (
            f"{model_info.format_pricing()} • "
            f"{model_info.context_length//1000}k context"
        )
        if model_info.recommended:
            description = "Recommended - " + description

        models.append({
            "id": model_info.id,
            "name": model_info.name,
            "description": description,
        })

    return models


def get_provider_choices() -> List[tuple[str, str, str]]:
    """Get provider choices for the wizard menu from registry.

    Returns:
        List of (id, name, description) tuples, sorted with popular providers first
    """
    registry = get_model_registry()
    providers = [
        (provider_info.id, provider_info.name, provider_info.description)
        for provider_info in registry.list_providers()
    ]

    # Define priority order for popular providers
    priority_providers = [
        "anthropic",
        "openai",
        "fireworks",
        "google",
        "deepseek",
        "groq",
        "mistral",
        "cohere",
        "perplexity",
        "together",
    ]

    def sort_key(provider: tuple[str, str, str]) -> tuple[int, str]:
        """Sort key: priority providers first, then alphabetical."""
        provider_id = provider[0]
        if provider_id in priority_providers:
            return (0, priority_providers.index(provider_id))
        return (1, provider[1].lower())  # Sort by name alphabetically

    return sorted(providers, key=sort_key)


# Legacy PROVIDERS dict for backward compatibility
PROVIDERS: Dict[str, Dict[str, Any]] = {
    provider_id: get_provider_config(provider_id)
    for provider_id in ["fireworks", "openai", "anthropic"]
}
