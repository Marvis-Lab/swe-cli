"""Model and provider configuration management."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models_dev_loader import load_models_dev_catalog

_LOG = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    """Information about a specific model."""

    id: str
    name: str
    provider: str
    context_length: int
    capabilities: List[str]
    pricing_input: float = 0.0
    pricing_output: float = 0.0
    pricing_unit: str = "per million tokens"
    serverless: bool = False
    tunable: bool = False
    recommended: bool = False
    max_tokens: Optional[int] = None

    def __str__(self) -> str:
        """String representation of model."""
        caps = ", ".join(self.capabilities)
        return (
            f"{self.name}\n"
            f"  Provider: {self.provider}\n"
            f"  Context: {self.context_length:,} tokens\n"
            f"  Capabilities: {caps}"
        )

    def format_pricing(self) -> str:
        """Format pricing for display."""
        if self.pricing_input == 0 and self.pricing_output == 0:
            return "N/A"
        return f"${self.pricing_input:.2f} in / ${self.pricing_output:.2f} out {self.pricing_unit}"


@dataclass
class ProviderInfo:
    """Information about a provider."""

    id: str
    name: str
    description: str
    api_key_env: str
    api_base_url: str
    models: Dict[str, ModelInfo]

    def list_models(self, capability: Optional[str] = None) -> List[ModelInfo]:
        """List all models, optionally filtered by capability."""
        models = list(self.models.values())
        if capability:
            models = [m for m in models if capability in m.capabilities]
        return sorted(models, key=lambda m: m.context_length, reverse=True)

    def get_recommended_model(self) -> Optional[ModelInfo]:
        """Get the recommended model for this provider."""
        for model in self.models.values():
            if model.recommended:
                return model
        # If no recommended, return first model
        return list(self.models.values())[0] if self.models else None


class ModelRegistry:
    """Registry for managing model and provider configurations."""

    def __init__(self, providers_dir: Optional[Path] = None):
        """Initialize model registry.

        Args:
            providers_dir: Path to providers directory containing JSON files
        """
        if providers_dir is None:
            providers_dir = Path(__file__).parent / "providers"

        self.providers_dir = providers_dir
        self.providers: Dict[str, ProviderInfo] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load model configuration from provider JSON files."""
        # Load all .json files from providers directory
        if not self.providers_dir.exists():
            # Fallback to legacy models.json if providers dir doesn't exist
            legacy_config = self.providers_dir.parent / "models.json"
            if legacy_config.exists():
                self._load_legacy_config(legacy_config)
            return

        for provider_file in self.providers_dir.glob("*.json"):
            with open(provider_file) as f:
                provider_data = json.load(f)

            provider_id = provider_data["id"]
            models = {}

            for model_key, model_data in provider_data["models"].items():
                pricing = model_data.get("pricing", {})
                models[model_key] = ModelInfo(
                    id=model_data["id"],
                    name=model_data["name"],
                    provider=model_data["provider"],
                    context_length=model_data["context_length"],
                    capabilities=model_data["capabilities"],
                    pricing_input=pricing.get("input", 0.0),
                    pricing_output=pricing.get("output", 0.0),
                    pricing_unit=pricing.get("unit", "per million tokens"),
                    serverless=model_data.get("serverless", False),
                    tunable=model_data.get("tunable", False),
                    recommended=model_data.get("recommended", False),
                    max_tokens=model_data.get("max_tokens"),
                )

            self.providers[provider_id] = ProviderInfo(
                id=provider_id,
                name=provider_data["name"],
                description=provider_data["description"],
                api_key_env=provider_data["api_key_env"],
                api_base_url=provider_data["api_base_url"],
                models=models,
            )

        self._augment_with_models_dev()

    def _augment_with_models_dev(self) -> None:
        """Merge providers/models from the Models.dev catalog."""

        catalog = load_models_dev_catalog()
        if not catalog:
            return

        existing = set(self.providers.keys())
        existing_names = {info.name.lower(): pid for pid, info in self.providers.items() if info.name}

        for provider_id, provider_data in catalog.items():
            provider_name = provider_data.get("name") or provider_id.title()
            provider_name_lower = provider_name.lower()

            if provider_id in existing or provider_name_lower in existing_names:
                continue

            models_block = provider_data.get("models") or {}
            if not models_block:
                continue

            converted_models: Dict[str, ModelInfo] = {}
            recommended_assigned = False

            for model_key, model_data in models_block.items():
                try:
                    converted = self._convert_models_dev_model(
                        provider_name=provider_name,
                        model_key=model_key,
                        model_data=model_data,
                        recommend_if_first=not recommended_assigned,
                    )
                except ValueError:
                    continue

                if not converted:
                    continue

                if converted.recommended:
                    recommended_assigned = True
                converted_models[model_key] = converted

            if not converted_models:
                continue

            description = provider_data.get("api", "") or f"{provider_name} via Models.dev"
            env_vars = provider_data.get("env") or []
            api_key_env = env_vars[0] if env_vars else ""
            api_base_url = provider_data.get("api") or ""

            self.providers[provider_id] = ProviderInfo(
                id=provider_id,
                name=provider_name,
                description=description,
                api_key_env=api_key_env,
                api_base_url=api_base_url,
                models=converted_models,
            )
            existing.add(provider_id)
            existing_names[provider_name.lower()] = provider_id
            _LOG.debug("Loaded %s models from Models.dev provider %s", len(converted_models), provider_id)

    def _convert_models_dev_model(
        self,
        *,
        provider_name: str,
        model_key: str,
        model_data: Dict[str, Any],
        recommend_if_first: bool,
    ) -> Optional[ModelInfo]:
        """Convert a models.dev model entry into ModelInfo."""

        model_id = model_data.get("id") or model_key
        model_name = model_data.get("name") or model_id

        limit = model_data.get("limit") or {}
        context_length = int(limit.get("context") or 0)
        if context_length <= 0:
            return None

        modalities = model_data.get("modalities") or {}
        input_modalities = modalities.get("input") or []
        output_modalities = modalities.get("output") or []

        if input_modalities and "text" not in input_modalities:
            # Skip pure non-text models (e.g., embeddings-only)
            return None

        cost = model_data.get("cost") or {}
        pricing_input = float(cost.get("input") or 0)
        pricing_output = float(cost.get("output") or 0)
        pricing_unit = cost.get("unit") or "per 1M tokens"

        capabilities = self._extract_capabilities(model_data, input_modalities, output_modalities)
        if "text" not in capabilities:
            capabilities.insert(0, "text")

        recommended = False
        status = model_data.get("status")
        if recommend_if_first or status == "beta":
            recommended = True

        return ModelInfo(
            id=model_id,
            name=model_name,
            provider=provider_name,
            pricing_input=pricing_input,
            pricing_output=pricing_output,
            pricing_unit=pricing_unit,
            context_length=context_length,
            capabilities=capabilities,
            recommended=recommended,
        )

    @staticmethod
    def _extract_capabilities(
        model_data: Dict[str, Any],
        input_modalities: List[str],
        output_modalities: List[str],
    ) -> List[str]:
        """Infer capability tags from models.dev fields."""

        capabilities: List[str] = []
        if not input_modalities or "text" in input_modalities:
            capabilities.append("text")
        if "image" in input_modalities or "image" in output_modalities:
            capabilities.append("vision")
        if model_data.get("reasoning"):
            capabilities.append("reasoning")
        if "audio" in input_modalities or "audio" in output_modalities:
            capabilities.append("audio")

        seen = set()
        deduped: List[str] = []
        for cap in capabilities:
            if cap not in seen:
                seen.add(cap)
                deduped.append(cap)
        return deduped

    def _load_legacy_config(self, config_path: Path) -> None:
        """Load legacy models.json format for backward compatibility."""
        with open(config_path) as f:
            data = json.load(f)

        for provider_id, provider_data in data["providers"].items():
            models = {}
            for model_key, model_data in provider_data["models"].items():
                pricing = model_data.get("pricing", {})
                models[model_key] = ModelInfo(
                    id=model_data["id"],
                    name=model_data["name"],
                    provider=model_data["provider"],
                    context_length=model_data["context_length"],
                    capabilities=model_data["capabilities"],
                    pricing_input=pricing.get("input", 0.0),
                    pricing_output=pricing.get("output", 0.0),
                    pricing_unit=pricing.get("unit", "per million tokens"),
                    serverless=model_data.get("serverless", False),
                    tunable=model_data.get("tunable", False),
                    recommended=model_data.get("recommended", False),
                    max_tokens=model_data.get("max_tokens"),
                )

            self.providers[provider_id] = ProviderInfo(
                id=provider_id,
                name=provider_data["name"],
                description=provider_data["description"],
                api_key_env=provider_data["api_key_env"],
                api_base_url=provider_data["api_base_url"],
                models=models,
            )

    def get_provider(self, provider_id: str) -> Optional[ProviderInfo]:
        """Get provider information by ID."""
        return self.providers.get(provider_id)

    def list_providers(self) -> List[ProviderInfo]:
        """List all available providers."""
        return list(self.providers.values())

    def get_model(self, provider_id: str, model_key: str) -> Optional[ModelInfo]:
        """Get model information by provider and model key."""
        provider = self.get_provider(provider_id)
        if provider:
            return provider.models.get(model_key)
        return None

    def find_model_by_id(self, model_id: str) -> Optional[tuple[str, str, ModelInfo]]:
        """Find a model by its full ID.

        Returns:
            Tuple of (provider_id, model_key, ModelInfo) or None
        """
        for provider_id, provider in self.providers.items():
            for model_key, model in provider.models.items():
                if model.id == model_id:
                    return (provider_id, model_key, model)
        return None

    def list_all_models(
        self,
        capability: Optional[str] = None,
        max_price: Optional[float] = None,
    ) -> List[tuple[str, ModelInfo]]:
        """List all models across all providers.

        Args:
            capability: Filter by capability (e.g., "vision", "code")
            max_price: Maximum output price per million tokens

        Returns:
            List of (provider_id, ModelInfo) tuples
        """
        models = []
        for provider_id, provider in self.providers.items():
            for model in provider.models.values():
                # Apply filters
                if capability and capability not in model.capabilities:
                    continue
                if max_price is not None and model.pricing_output > max_price:
                    continue
                models.append((provider_id, model))

        # Sort by price (output tokens)
        return sorted(models, key=lambda x: x[1].pricing_output)


# Global registry instance
_registry: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    """Get the global model registry instance."""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
