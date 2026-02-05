"""Tests for ConfigManager model handling (swecli/core/runtime/config.py)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from swecli.core.runtime.config import ConfigManager
from swecli.models.config import AppConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _mock_paths(tmp_path):
    """Return a mock paths object that points into tmp_path."""
    paths = MagicMock()
    paths.global_settings = tmp_path / "global" / "settings.json"
    paths.project_settings = tmp_path / "project" / ".swecli" / "settings.json"
    paths.global_context_file = tmp_path / "global" / "OPENCLI.md"
    paths.global_skills_dir = tmp_path / "global" / "skills"
    paths.project_skills_dir = tmp_path / "project" / ".swecli" / "skills"
    paths.global_agents_file = tmp_path / "global" / "agents.json"
    paths.global_agents_dir = tmp_path / "global" / "agents"
    paths.project_agents_file = tmp_path / "project" / ".swecli" / "agents.json"
    paths.project_agents_dir = tmp_path / "project" / ".swecli" / "agents"
    return paths


# ---------------------------------------------------------------------------
# Tests: load_config model fields
# ---------------------------------------------------------------------------

class TestConfigManagerLoadConfig:
    """Test that model-related fields load correctly from settings files."""

    def test_loads_model_provider_from_global(self, tmp_path):
        paths = _mock_paths(tmp_path)
        _write_settings(paths.global_settings, {
            "model_provider": "openai",
            "model": "gpt-4o",
        })

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            config = cm.load_config()

        assert config.model_provider == "openai"
        assert config.model == "gpt-4o"

    def test_loads_thinking_model(self, tmp_path):
        paths = _mock_paths(tmp_path)
        _write_settings(paths.global_settings, {
            "model_provider": "fireworks",
            "model": "accounts/fireworks/models/some-model",
            "model_thinking_provider": "openai",
            "model_thinking": "o3",
        })

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            config = cm.load_config()

        assert config.model_thinking_provider == "openai"
        assert config.model_thinking == "o3"

    def test_loads_vlm_model(self, tmp_path):
        paths = _mock_paths(tmp_path)
        _write_settings(paths.global_settings, {
            "model_provider": "openai",
            "model": "gpt-4o",
            "model_vlm_provider": "openai",
            "model_vlm": "gpt-4o",
        })

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            config = cm.load_config()

        assert config.model_vlm_provider == "openai"
        assert config.model_vlm == "gpt-4o"

    def test_local_overrides_global(self, tmp_path):
        """Local project config should override global config."""
        paths = _mock_paths(tmp_path)
        _write_settings(paths.global_settings, {
            "model_provider": "openai",
            "model": "gpt-4o",
        })
        _write_settings(paths.project_settings, {
            "model_provider": "anthropic",
            "model": "claude-opus-4-5-20251101",
        })

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            config = cm.load_config()

        assert config.model_provider == "anthropic"
        assert config.model == "claude-opus-4-5-20251101"

    def test_defaults_when_no_config_files(self, tmp_path):
        """Should use AppConfig defaults when no config files exist."""
        paths = _mock_paths(tmp_path)

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            config = cm.load_config()

        assert config.model_provider == "fireworks"
        assert config.model_thinking is None
        assert config.model_vlm is None


# ---------------------------------------------------------------------------
# Tests: Fireworks model normalization
# ---------------------------------------------------------------------------

class TestFireworksNormalization:
    """Test Fireworks model ID normalization."""

    def test_normalize_short_fireworks_model(self):
        data = {
            "model_provider": "fireworks",
            "model": "qwen-72b",
        }
        result, changed = ConfigManager._normalize_fireworks_models(data)
        assert changed is True
        assert result["model"] == "accounts/fireworks/models/qwen-72b"

    def test_already_normalized_not_changed(self):
        data = {
            "model_provider": "fireworks",
            "model": "accounts/fireworks/models/qwen-72b",
        }
        result, changed = ConfigManager._normalize_fireworks_models(data)
        assert changed is False

    def test_non_fireworks_provider_not_touched(self):
        data = {
            "model_provider": "openai",
            "model": "gpt-4o",
        }
        result, changed = ConfigManager._normalize_fireworks_models(data)
        assert changed is False
        assert result["model"] == "gpt-4o"

    def test_normalizes_thinking_model(self):
        data = {
            "model_provider": "openai",
            "model": "gpt-4o",
            "model_thinking_provider": "fireworks",
            "model_thinking": "deepseek-r1",
        }
        result, changed = ConfigManager._normalize_fireworks_models(data)
        assert changed is True
        assert result["model_thinking"] == "accounts/fireworks/models/deepseek-r1"

    def test_normalizes_vlm_model(self):
        data = {
            "model_provider": "openai",
            "model": "gpt-4o",
            "model_vlm_provider": "fireworks",
            "model_vlm": "some-vlm-model",
        }
        result, changed = ConfigManager._normalize_fireworks_models(data)
        assert changed is True
        assert result["model_vlm"] == "accounts/fireworks/models/some-vlm-model"

    def test_normalizes_all_three_slots(self):
        data = {
            "model_provider": "fireworks",
            "model": "model-a",
            "model_thinking_provider": "fireworks",
            "model_thinking": "model-b",
            "model_vlm_provider": "fireworks",
            "model_vlm": "model-c",
        }
        result, changed = ConfigManager._normalize_fireworks_models(data)
        assert changed is True
        assert result["model"] == "accounts/fireworks/models/model-a"
        assert result["model_thinking"] == "accounts/fireworks/models/model-b"
        assert result["model_vlm"] == "accounts/fireworks/models/model-c"

    def test_empty_model_not_normalized(self):
        data = {
            "model_provider": "fireworks",
            "model": "",
        }
        result, changed = ConfigManager._normalize_fireworks_models(data)
        assert changed is False

    def test_strips_slug_from_path(self):
        """Model IDs like 'org/model-name' should extract just the slug."""
        data = {
            "model_provider": "fireworks",
            "model": "some-org/my-model",
        }
        result, changed = ConfigManager._normalize_fireworks_models(data)
        assert changed is True
        assert result["model"] == "accounts/fireworks/models/my-model"


# ---------------------------------------------------------------------------
# Tests: save_config
# ---------------------------------------------------------------------------

class TestConfigManagerSaveConfig:
    """Test saving model-related config fields."""

    def test_saves_model_fields(self, tmp_path):
        paths = _mock_paths(tmp_path)

        config = AppConfig(
            model_provider="openai",
            model="gpt-4o",
            model_thinking_provider="openai",
            model_thinking="o3",
            model_vlm_provider="anthropic",
            model_vlm="claude-opus-4-5-20251101",
        )

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            cm.save_config(config, global_config=True)

        with open(paths.global_settings) as f:
            saved = json.load(f)

        assert saved["model_provider"] == "openai"
        assert saved["model"] == "gpt-4o"
        assert saved["model_thinking_provider"] == "openai"
        assert saved["model_thinking"] == "o3"
        assert saved["model_vlm_provider"] == "anthropic"
        assert saved["model_vlm"] == "claude-opus-4-5-20251101"

    def test_does_not_save_api_key(self, tmp_path):
        """API key should never be saved to disk."""
        paths = _mock_paths(tmp_path)

        config = AppConfig(
            model_provider="openai",
            model="gpt-4o",
            api_key="secret-key",
        )

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            cm.save_config(config, global_config=True)

        with open(paths.global_settings) as f:
            saved = json.load(f)

        assert "api_key" not in saved

    def test_does_not_save_none_values(self, tmp_path):
        """None values should be excluded from saved config."""
        paths = _mock_paths(tmp_path)

        config = AppConfig(
            model_provider="openai",
            model="gpt-4o",
            model_thinking=None,
            model_vlm=None,
        )

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            cm.save_config(config, global_config=True)

        with open(paths.global_settings) as f:
            saved = json.load(f)

        assert "model_thinking" not in saved
        assert "model_vlm" not in saved

    def test_save_to_project_config(self, tmp_path):
        paths = _mock_paths(tmp_path)

        config = AppConfig(model_provider="anthropic", model="claude-sonnet-4-5-20250929")

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            cm.save_config(config, global_config=False)

        assert paths.project_settings.exists()
        with open(paths.project_settings) as f:
            saved = json.load(f)
        assert saved["model_provider"] == "anthropic"


# ---------------------------------------------------------------------------
# Tests: max_context_tokens auto-calculation
# ---------------------------------------------------------------------------

class TestMaxContextTokensAutoCalc:
    """Test automatic max_context_tokens from model's context_length."""

    def test_auto_set_from_model_registry(self, tmp_path):
        """max_context_tokens should be 80% of model's context_length."""
        paths = _mock_paths(tmp_path)
        _write_settings(paths.global_settings, {
            "model_provider": "openai",
            "model": "gpt-4o",
        })

        mock_model_info = MagicMock()
        mock_model_info.context_length = 128000

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            with patch.object(AppConfig, "get_model_info", return_value=mock_model_info):
                config = cm.load_config()

        assert config.max_context_tokens == int(128000 * 0.8)

    def test_explicitly_set_context_tokens_preserved(self, tmp_path):
        """Explicitly set max_context_tokens (non-default) should be preserved."""
        paths = _mock_paths(tmp_path)
        _write_settings(paths.global_settings, {
            "model_provider": "openai",
            "model": "gpt-4o",
            "max_context_tokens": 50000,
        })

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            config = cm.load_config()

        assert config.max_context_tokens == 50000

    def test_old_default_replaced(self, tmp_path):
        """Old defaults (100000 or 256000) should be auto-replaced."""
        paths = _mock_paths(tmp_path)
        _write_settings(paths.global_settings, {
            "model_provider": "openai",
            "model": "gpt-4o",
            "max_context_tokens": 100000,
        })

        mock_model_info = MagicMock()
        mock_model_info.context_length = 200000

        with patch("swecli.core.runtime.config.get_paths", return_value=paths):
            cm = ConfigManager(working_dir=tmp_path / "project")
            with patch.object(AppConfig, "get_model_info", return_value=mock_model_info):
                config = cm.load_config()

        assert config.max_context_tokens == int(200000 * 0.8)
