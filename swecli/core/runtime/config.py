"""Configuration management with hierarchical loading."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from swecli.models.config import AppConfig

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages hierarchical configuration loading and merging."""

    def __init__(self, working_dir: Path | None = None):
        """Initialize config manager.

        Args:
            working_dir: Current working directory (defaults to cwd)
        """
        self.working_dir = working_dir or Path.cwd()
        self._config: AppConfig | None = None

    def load_config(self) -> AppConfig:
        """Load and merge configuration from multiple sources.

        Priority (highest to lowest):
        1. Local project config (.swecli/settings.json)
        2. Global user config (~/.swecli/settings.json)
        3. Default values
        """
        # Start with defaults
        config_data: dict = {}
        global_data: dict = {}
        local_data: dict = {}

        # Load global config
        global_config = Path.home() / ".swecli" / "settings.json"
        if global_config.exists():
            with open(global_config) as f:
                global_data = json.load(f)
                # Remove legacy api_key from config - keys should come from environment
                global_data.pop("api_key", None)
                _, global_changed = self._normalize_fireworks_models(global_data)
                if global_changed:
                    with open(global_config, "w") as target:
                        json.dump(global_data, target, indent=2)
                config_data.update(global_data)

        # Load local project config
        local_config = self.working_dir / ".swecli" / "settings.json"
        if local_config.exists():
            with open(local_config) as f:
                local_data = json.load(f)
                # Remove legacy api_key from config - keys should come from environment
                local_data.pop("api_key", None)
                _, local_changed = self._normalize_fireworks_models(local_data)
                if local_changed:
                    with open(local_config, "w") as target:
                        json.dump(local_data, target, indent=2)
                config_data.update(local_data)

        self._normalize_fireworks_models(config_data)

        # Create AppConfig with merged data
        self._config = AppConfig(**config_data)

        # Auto-set max_context_tokens from model if:
        # 1. Not explicitly configured, OR
        # 2. Set to old defaults (100000 or 256000)
        current_max = config_data.get("max_context_tokens")
        if current_max is None or current_max in [100000, 256000]:
            model_info = self._config.get_model_info()
            if model_info and model_info.context_length:
                # Use 80% of context length to leave room for response
                self._config.max_context_tokens = int(model_info.context_length * 0.8)

        return self._config

    def get_config(self) -> AppConfig:
        """Get current config, loading if necessary."""
        if self._config is None:
            return self.load_config()
        return self._config

    def save_config(self, config: AppConfig, global_config: bool = False) -> None:
        """Save configuration to file.

        Args:
            config: Configuration to save
            global_config: If True, save to global config; otherwise save to local project
        """
        if global_config:
            config_path = Path.home() / ".swecli" / "settings.json"
        else:
            config_path = self.working_dir / ".swecli" / "settings.json"

        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Only save user-facing settings, not internal defaults
        # Note: api_key is intentionally excluded - keys should come from
        # environment variables for security and to avoid cross-provider issues
        user_fields = {
            "model_provider",
            "model",
            "model_thinking_provider",
            "model_thinking",
            "model_vlm_provider",
            "model_vlm",
            "api_base_url",
            "debug_logging",
        }
        data = {k: v for k, v in config.model_dump().items() if k in user_fields and v is not None}
        with open(config_path, "w") as f:
            json.dump(data, f, indent=2)

    def ensure_directories(self) -> None:
        """Ensure all required directories exist."""
        config = self.get_config()

        # Expand paths
        swecli_dir = Path(config.swecli_dir).expanduser()
        session_dir = Path(config.session_dir).expanduser()
        log_dir = Path(config.log_dir).expanduser()

        # Create directories
        swecli_dir.mkdir(parents=True, exist_ok=True)
        session_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create user skills directory
        self.user_skills_dir.mkdir(parents=True, exist_ok=True)

        # Create local command directory if in a project
        local_cmd_dir = self.working_dir / config.command_dir
        if not local_cmd_dir.exists() and (self.working_dir / ".git").exists():
            local_cmd_dir.mkdir(parents=True, exist_ok=True)

    def load_context_files(self) -> list[str]:
        """Load OPENCLI.md context files hierarchically.

        Returns:
            List of context file contents, from global to local
        """
        contexts = []

        # Global context
        global_context = Path.home() / ".swecli" / "OPENCLI.md"
        if global_context.exists():
            contexts.append(global_context.read_text())

        # Project root context
        project_context = self.working_dir / "OPENCLI.md"
        if project_context.exists():
            contexts.append(project_context.read_text())

        # Subdirectory contexts (walk up from current dir to project root)
        current = self.working_dir
        while current != current.parent:
            subdir_context = current / "OPENCLI.md"
            if subdir_context.exists() and subdir_context != project_context:
                contexts.insert(1, subdir_context.read_text())  # Insert after global
            current = current.parent

        return contexts

    @staticmethod
    def _normalize_fireworks_models(data: dict) -> tuple[dict, bool]:
        """Normalize Fireworks model identifiers to full registry IDs."""
        changed = False
        mapping = [
            ("model_provider", "model"),
            ("model_thinking_provider", "model_thinking"),
            ("model_vlm_provider", "model_vlm"),
        ]

        for provider_key, model_key in mapping:
            provider_id = data.get(provider_key)
            model_id = data.get(model_key)
            if provider_id != "fireworks":
                continue
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            normalized = model_id.strip()
            if normalized.startswith("accounts/"):
                continue
            slug = normalized.split("/")[-1]
            corrected = f"accounts/fireworks/models/{slug}"
            if normalized != corrected:
                data[model_key] = corrected
                changed = True

        return data, changed

    # ===== Skills System Support =====

    @property
    def user_skills_dir(self) -> Path:
        """Get user-global skills directory (~/.swecli/skills/)."""
        return Path.home() / ".swecli" / "skills"

    @property
    def project_skills_dir(self) -> Path | None:
        """Get project-local skills directory (<project>/.swecli/skills/).

        Returns None if no working directory is set.
        """
        if self.working_dir:
            return self.working_dir / ".swecli" / "skills"
        return None

    def get_skill_dirs(self) -> list[Path]:
        """Get all skill directories in priority order (project first, then user).

        Returns:
            List of existing skill directories, highest priority first
        """
        dirs = []
        # Project skills take priority
        if self.project_skills_dir and self.project_skills_dir.exists():
            dirs.append(self.project_skills_dir)
        # User global skills
        if self.user_skills_dir.exists():
            dirs.append(self.user_skills_dir)
        return dirs

    def load_custom_agents(self) -> list[dict[str, Any]]:
        """Load custom agent definitions from config files.

        Loads from:
        1. ~/.swecli/agents.json (user global)
        2. <project>/.swecli/agents.json (project local, takes priority)

        Returns:
            List of agent definitions merged from all sources
        """
        agents: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        # Load user global agents
        global_agents_file = Path.home() / ".swecli" / "agents.json"
        if global_agents_file.exists():
            try:
                with open(global_agents_file) as f:
                    data = json.load(f)
                    for agent in data.get("agents", []):
                        if agent.get("name") and agent["name"] not in seen_names:
                            agent["_source"] = "user-global"
                            agents.append(agent)
                            seen_names.add(agent["name"])
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load global agents.json: {e}")

        # Load project agents (override user global)
        if self.working_dir:
            project_agents_file = self.working_dir / ".swecli" / "agents.json"
            if project_agents_file.exists():
                try:
                    with open(project_agents_file) as f:
                        data = json.load(f)
                        for agent in data.get("agents", []):
                            name = agent.get("name")
                            if name:
                                # Remove existing agent with same name (project overrides)
                                agents = [a for a in agents if a.get("name") != name]
                                agent["_source"] = "project"
                                agents.append(agent)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"Failed to load project agents.json: {e}")

        return agents
