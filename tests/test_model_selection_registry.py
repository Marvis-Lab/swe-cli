"""Tests for ModelRegistry model selection features (swecli/config/models.py)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from swecli.config.models import ModelInfo, ModelRegistry, ProviderInfo, get_model_registry


# ---------------------------------------------------------------------------
# Fixtures: small in-memory provider data
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_provider_data():
    """Create sample provider JSON data for testing."""
    return {
        "id": "test_provider",
        "name": "Test Provider",
        "description": "Test provider for unit tests",
        "api_key_env": "TEST_API_KEY",
        "api_base_url": "https://api.test.com/v1",
        "models": {
            "test-model-1": {
                "id": "test-model-1",
                "name": "Test Model 1",
                "provider": "Test Provider",
                "context_length": 128000,
                "capabilities": ["text", "vision", "reasoning"],
                "recommended": True,
                "supports_temperature": True,
            },
            "test-model-2": {
                "id": "test-model-2",
                "name": "Test Model 2",
                "provider": "Test Provider",
                "context_length": 32000,
                "capabilities": ["text"],
                "supports_temperature": True,
            },
            "test-reasoning": {
                "id": "test-reasoning",
                "name": "Test Reasoning",
                "provider": "Test Provider",
                "context_length": 200000,
                "capabilities": ["text", "reasoning"],
                "supports_temperature": False,
            },
        },
    }


@pytest.fixture
def providers_dir(sample_provider_data, tmp_path):
    """Create a temp providers directory with test data."""
    providers = tmp_path / "providers"
    providers.mkdir()
    with open(providers / "test_provider.json", "w") as f:
        json.dump(sample_provider_data, f)
    return providers


@pytest.fixture
def registry(providers_dir):
    """Create a ModelRegistry using the temp providers directory."""
    with patch("swecli.config.models.load_models_dev_catalog", return_value=None):
        return ModelRegistry(providers_dir=providers_dir)


# ---------------------------------------------------------------------------
# ModelInfo tests
# ---------------------------------------------------------------------------

class TestModelInfo:
    """Test ModelInfo dataclass."""

    def test_basic_creation(self):
        model = ModelInfo(
            id="gpt-4o",
            name="GPT-4o",
            provider="OpenAI",
            context_length=128000,
            capabilities=["text", "vision"],
        )
        assert model.id == "gpt-4o"
        assert model.name == "GPT-4o"
        assert model.context_length == 128000
        assert "vision" in model.capabilities

    def test_default_values(self):
        model = ModelInfo(
            id="m1", name="M1", provider="P", context_length=1000, capabilities=["text"]
        )
        assert model.pricing_input == 0.0
        assert model.pricing_output == 0.0
        assert model.supports_temperature is True
        assert model.recommended is False
        assert model.max_tokens is None

    def test_supports_temperature_false(self):
        model = ModelInfo(
            id="o1",
            name="O1",
            provider="OpenAI",
            context_length=200000,
            capabilities=["text", "reasoning"],
            supports_temperature=False,
        )
        assert model.supports_temperature is False

    def test_format_pricing_with_values(self):
        model = ModelInfo(
            id="m", name="M", provider="P", context_length=1000, capabilities=["text"],
            pricing_input=2.50, pricing_output=10.00,
        )
        result = model.format_pricing()
        assert "$2.50" in result
        assert "$10.00" in result

    def test_format_pricing_na(self):
        model = ModelInfo(
            id="m", name="M", provider="P", context_length=1000, capabilities=["text"],
        )
        assert model.format_pricing() == "N/A"

    def test_str_representation(self):
        model = ModelInfo(
            id="m", name="Test Model", provider="P", context_length=128000,
            capabilities=["text", "vision"],
        )
        text = str(model)
        assert "Test Model" in text
        assert "128,000" in text
        assert "text, vision" in text


# ---------------------------------------------------------------------------
# ProviderInfo tests
# ---------------------------------------------------------------------------

class TestProviderInfo:
    """Test ProviderInfo dataclass."""

    def _make_provider(self):
        models = {
            "m1": ModelInfo(
                id="m1", name="M1", provider="P", context_length=128000,
                capabilities=["text", "vision"], recommended=True,
            ),
            "m2": ModelInfo(
                id="m2", name="M2", provider="P", context_length=32000,
                capabilities=["text"],
            ),
            "m3": ModelInfo(
                id="m3", name="M3", provider="P", context_length=200000,
                capabilities=["text", "reasoning"],
            ),
        }
        return ProviderInfo(
            id="test", name="Test", description="Test desc",
            api_key_env="TEST_KEY", api_base_url="https://test.com",
            models=models,
        )

    def test_list_models_all(self):
        provider = self._make_provider()
        models = provider.list_models()
        assert len(models) == 3

    def test_list_models_sorted_by_context_length(self):
        provider = self._make_provider()
        models = provider.list_models()
        assert models[0].context_length >= models[1].context_length

    def test_list_models_filter_by_capability(self):
        provider = self._make_provider()
        vision_models = provider.list_models(capability="vision")
        assert len(vision_models) == 1
        assert vision_models[0].id == "m1"

    def test_list_models_filter_reasoning(self):
        provider = self._make_provider()
        reasoning = provider.list_models(capability="reasoning")
        assert len(reasoning) == 1
        assert reasoning[0].id == "m3"

    def test_list_models_filter_no_match(self):
        provider = self._make_provider()
        result = provider.list_models(capability="audio")
        assert len(result) == 0

    def test_get_recommended_model(self):
        provider = self._make_provider()
        rec = provider.get_recommended_model()
        assert rec is not None
        assert rec.recommended is True
        assert rec.id == "m1"

    def test_get_recommended_model_fallback(self):
        """When no model is recommended, return the first one."""
        models = {
            "m1": ModelInfo(
                id="m1", name="M1", provider="P", context_length=1000,
                capabilities=["text"],
            ),
        }
        provider = ProviderInfo(
            id="test", name="Test", description="", api_key_env="", api_base_url="",
            models=models,
        )
        rec = provider.get_recommended_model()
        assert rec is not None
        assert rec.id == "m1"

    def test_get_recommended_model_empty(self):
        provider = ProviderInfo(
            id="test", name="Test", description="", api_key_env="", api_base_url="",
            models={},
        )
        assert provider.get_recommended_model() is None


# ---------------------------------------------------------------------------
# ModelRegistry tests
# ---------------------------------------------------------------------------

class TestModelRegistry:
    """Test ModelRegistry model lookup and filtering."""

    def test_load_providers(self, registry):
        assert len(registry.providers) == 1
        assert "test_provider" in registry.providers

    def test_get_provider(self, registry):
        provider = registry.get_provider("test_provider")
        assert provider is not None
        assert provider.name == "Test Provider"

    def test_get_provider_not_found(self, registry):
        assert registry.get_provider("nonexistent") is None

    def test_list_providers(self, registry):
        providers = registry.list_providers()
        assert len(providers) == 1

    def test_get_model(self, registry):
        model = registry.get_model("test_provider", "test-model-1")
        assert model is not None
        assert model.id == "test-model-1"

    def test_get_model_not_found(self, registry):
        assert registry.get_model("test_provider", "nonexistent") is None
        assert registry.get_model("nonexistent", "test-model-1") is None

    def test_find_model_by_id(self, registry):
        result = registry.find_model_by_id("test-model-1")
        assert result is not None
        provider_id, model_key, model_info = result
        assert provider_id == "test_provider"
        assert model_key == "test-model-1"
        assert model_info.name == "Test Model 1"

    def test_find_model_by_id_not_found(self, registry):
        assert registry.find_model_by_id("nonexistent-model") is None

    def test_list_all_models(self, registry):
        models = registry.list_all_models()
        assert len(models) == 3

    def test_list_all_models_filter_capability(self, registry):
        vision_models = registry.list_all_models(capability="vision")
        assert len(vision_models) == 1
        assert vision_models[0][1].id == "test-model-1"

    def test_list_all_models_filter_reasoning(self, registry):
        reasoning = registry.list_all_models(capability="reasoning")
        assert len(reasoning) == 2  # test-model-1 and test-reasoning

    def test_list_all_models_filter_max_price(self, registry):
        models = registry.list_all_models(max_price=0.0)
        # All models have 0.0 pricing, so all should be included
        assert len(models) == 3

    def test_list_all_models_sorted_by_price(self, registry):
        models = registry.list_all_models()
        prices = [m[1].pricing_output for m in models]
        assert prices == sorted(prices)

    def test_supports_temperature_loaded(self, registry):
        reasoning = registry.find_model_by_id("test-reasoning")
        assert reasoning is not None
        assert reasoning[2].supports_temperature is False

        model1 = registry.find_model_by_id("test-model-1")
        assert model1 is not None
        assert model1[2].supports_temperature is True


class TestModelRegistryMultipleProviders:
    """Test registry with multiple providers."""

    def test_find_model_across_providers(self, tmp_path):
        """Models should be findable across different providers."""
        providers = tmp_path / "providers"
        providers.mkdir()

        for pid, model_id, model_name in [
            ("provider_a", "model-a", "Model A"),
            ("provider_b", "model-b", "Model B"),
        ]:
            data = {
                "id": pid,
                "name": pid.title(),
                "description": "",
                "api_key_env": f"{pid.upper()}_KEY",
                "api_base_url": f"https://{pid}.com",
                "models": {
                    model_id: {
                        "id": model_id,
                        "name": model_name,
                        "provider": pid.title(),
                        "context_length": 128000,
                        "capabilities": ["text"],
                    }
                },
            }
            with open(providers / f"{pid}.json", "w") as f:
                json.dump(data, f)

        with patch("swecli.config.models.load_models_dev_catalog", return_value=None):
            registry = ModelRegistry(providers_dir=providers)

        assert registry.find_model_by_id("model-a") is not None
        assert registry.find_model_by_id("model-b") is not None
        assert registry.find_model_by_id("model-a")[0] == "provider_a"
        assert registry.find_model_by_id("model-b")[0] == "provider_b"


class TestModelRegistryLegacyConfig:
    """Test legacy config loading fallback."""

    def test_loads_legacy_when_no_providers_dir(self, tmp_path):
        """Should load from models.json when providers/ doesn't exist."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        legacy_data = {
            "providers": {
                "legacy_prov": {
                    "name": "Legacy",
                    "description": "Legacy provider",
                    "api_key_env": "LEGACY_KEY",
                    "api_base_url": "https://legacy.com",
                    "models": {
                        "legacy-model": {
                            "id": "legacy-model",
                            "name": "Legacy Model",
                            "provider": "Legacy",
                            "context_length": 4096,
                            "capabilities": ["text"],
                        }
                    },
                }
            }
        }
        with open(config_dir / "models.json", "w") as f:
            json.dump(legacy_data, f)

        # providers/ dir doesn't exist, but models.json is at parent level
        providers_dir = config_dir / "providers"  # doesn't exist
        registry = ModelRegistry(providers_dir=providers_dir)

        assert "legacy_prov" in registry.providers
        model = registry.find_model_by_id("legacy-model")
        assert model is not None


class TestModelRegistryExtractCapabilities:
    """Test capability extraction logic."""

    def test_text_capability_default(self):
        caps = ModelRegistry._extract_capabilities({}, [], [])
        assert "text" in caps

    def test_vision_from_image_input(self):
        caps = ModelRegistry._extract_capabilities({}, ["text", "image"], [])
        assert "vision" in caps

    def test_vision_from_image_output(self):
        caps = ModelRegistry._extract_capabilities({}, ["text"], ["image"])
        assert "vision" in caps

    def test_reasoning_from_model_data(self):
        caps = ModelRegistry._extract_capabilities({"reasoning": True}, ["text"], [])
        assert "reasoning" in caps

    def test_no_reasoning_when_false(self):
        caps = ModelRegistry._extract_capabilities({"reasoning": False}, ["text"], [])
        assert "reasoning" not in caps

    def test_audio_capability(self):
        caps = ModelRegistry._extract_capabilities({}, ["text", "audio"], [])
        assert "audio" in caps

    def test_deduplication(self):
        """Capabilities should not be duplicated."""
        caps = ModelRegistry._extract_capabilities(
            {}, ["text", "text", "image"], ["image"]
        )
        assert caps.count("text") == 1
        assert caps.count("vision") == 1


class TestGlobalRegistrySingleton:
    """Test the global registry singleton."""

    def test_get_model_registry_returns_instance(self):
        import swecli.config.models as models_mod
        old = models_mod._registry
        try:
            models_mod._registry = None
            reg = get_model_registry()
            assert isinstance(reg, ModelRegistry)
            # Second call returns same instance
            assert get_model_registry() is reg
        finally:
            models_mod._registry = old

    def test_get_model_registry_caches(self):
        import swecli.config.models as models_mod
        old = models_mod._registry
        try:
            models_mod._registry = None
            reg1 = get_model_registry()
            reg2 = get_model_registry()
            assert reg1 is reg2
        finally:
            models_mod._registry = old
