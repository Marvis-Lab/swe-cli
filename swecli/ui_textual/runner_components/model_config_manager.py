"""Model configuration management for TextualRunner.

This module handles model configuration, switching, and UI updates for model slots.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from swecli.core.runtime import ConfigManager
from swecli.repl.repl import REPL


class ModelConfigManager:
    """Manages model configuration, selection, and UI updates."""

    def __init__(
        self,
        config_manager: ConfigManager,
        repl: REPL,
    ) -> None:
        """Initialize the manager.
        
        Args:
            config_manager: Configuration manager instance.
            repl: REPL instance for agent rebuilding and commands.
        """
        self._config_manager = config_manager
        self._repl = repl
        self._app: Any | None = None

    def set_app(self, app: Any) -> None:
        """Set the Textual app instance for UI updates."""
        self._app = app

    def get_model_config_snapshot(self) -> dict[str, dict[str, str]]:
        """Return current model configuration details for the UI."""
        config = self._config_manager.get_config()

        try:
            from swecli.config import get_model_registry

            registry = get_model_registry()
        except Exception:  # pragma: no cover - defensive
            registry = None

        def resolve(
            provider_id: Optional[str], model_id: Optional[str]
        ) -> dict[str, str]:
            if not provider_id or not model_id:
                return {}

            provider_display = provider_id.capitalize()
            model_display = model_id

            if registry is not None:
                provider_info = registry.get_provider(provider_id)
                if provider_info:
                    provider_display = provider_info.name
                found = registry.find_model_by_id(model_id)
                if found:
                    _, _, model_info = found
                    model_display = model_info.name
            else:
                if "/" in model_id:
                    model_display = model_id.split("/")[-1]

            return {
                "provider": provider_id,
                "provider_display": provider_display,
                "model": model_id,
                "model_display": model_display,
            }

        snapshot: dict[str, dict[str, str]] = {}
        snapshot["normal"] = resolve(config.model_provider, config.model)

        thinking_entry = resolve(
            config.model_thinking_provider, config.model_thinking
        )
        if thinking_entry:
            snapshot["thinking"] = thinking_entry

        vision_entry = resolve(config.model_vlm_provider, config.model_vlm)
        if vision_entry:
            snapshot["vision"] = vision_entry

        return snapshot

    def refresh_ui_config(self) -> None:
        """Refresh cached config-driven UI indicators after config changes."""
        if not self._app:
            return

        # Refresh cached config instance (commands may mutate or reload it)
        config = self._config_manager.get_config()
        model_display = f"{config.model_provider}/{config.model}"

        if hasattr(self._app, "update_primary_model"):
            self._app.update_primary_model(model_display)
        if hasattr(self._app, "update_model_slots"):
            self._app.update_model_slots(self._build_model_slots())

    async def apply_model_selection(
        self, slot: str, provider_id: str, model_id: str
    ) -> Any:
        """Apply a model selection coming from the Textual UI."""
        # This calls internal repl methods.
        # We assume repl.config_commands exists and has _switch_to_model
        if not hasattr(self._repl, "config_commands"):
             # Fallback if config_commands not available (e.g. dummy repl)
             from types import SimpleNamespace
             return SimpleNamespace(success=False, message="Config commands not available")

        result = await asyncio.to_thread(
            self._repl.config_commands._switch_to_model,
            provider_id,
            model_id,
            slot,
        )
        if result.success:
            # Rebuild agents with new config (needed for API key changes)
            await asyncio.to_thread(self._repl.rebuild_agents)
            self.refresh_ui_config()
        return result

    def _build_model_slots(self) -> dict[str, tuple[str, str]]:
        """Prepare formatted model slot information for the footer."""
        config = self._config_manager.get_config()

        def format_model(
            provider: Optional[str],
            model_id: Optional[str],
        ) -> tuple[str, str] | None:
            if not model_id:
                return None
            provider_display = provider.capitalize() if provider else "Unknown"
            if "/" in model_id:
                model_short = model_id.split("/")[-1]
            else:
                model_short = model_id
            return (provider_display, model_short)

        slots = {}
        normal = format_model(config.model_provider, config.model)
        if normal:
            slots["normal"] = normal

        if config.model_thinking and config.model_thinking != config.model:
            thinking = format_model(
                config.model_thinking_provider,
                config.model_thinking,
            )
            if thinking:
                slots["thinking"] = thinking

        if config.model_vlm and config.model_vlm != config.model:
            vision = format_model(
                config.model_vlm_provider,
                config.model_vlm,
            )
            if vision:
                slots["vision"] = vision

        return slots
