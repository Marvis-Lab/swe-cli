"""Interactive setup wizard for first-time configuration."""

import json
import os
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from .providers import get_provider_config, get_provider_choices, get_provider_models
from .validator import validate_api_key
from .interactive_menu import InteractiveMenu
from swecli.core.paths import get_paths, APP_DIR_NAME
from swecli.ui_textual.style_tokens import ERROR, SUCCESS, WARNING


console = Console()


def run_setup_wizard() -> bool:
    """Run the interactive setup wizard.

    Returns:
        True if setup completed successfully, False otherwise
    """
    console.print()
    console.print(
        Panel(
            "[bold cyan]Welcome to OpenDev! [/bold cyan]\n\n"
            "First-time setup detected.\n"
            "Let's configure your AI provider.",
            title="Setup Wizard",
            border_style="cyan",
        )
    )
    console.print()

    # Step 1: Select provider
    provider_id = select_provider()
    if not provider_id:
        return False

    provider_config = get_provider_config(provider_id)
    if not provider_config:
        console.print(f"[{ERROR}]Error: Provider '{provider_id}' not found[/{ERROR}]")
        return False

    # Step 2: Get API key
    api_key = get_api_key(provider_id, provider_config)
    if not api_key:
        return False

    # Step 3: Validate API key (optional)
    if Confirm.ask(f"\n[{WARNING}]Validate API key?[/{WARNING}]", default=True):
        if not validate_key(provider_id, api_key):
            console.print(
                f"[{WARNING}]Continuing without validation. "
                f"You may encounter errors if the key is invalid.[/{WARNING}]"
            )

    # Step 4: Select model
    model_id = select_model(provider_id, provider_config)
    if not model_id:
        return False

    # Look up model info for smart defaults
    from swecli.config import get_model_registry

    registry = get_model_registry()
    normal_model_result = registry.find_model_by_id(model_id)
    normal_model_info = normal_model_result[2] if normal_model_result else None

    collected_keys: dict[str, str] = {provider_id: api_key}

    # Step 5: Thinking model
    thinking_provider, thinking_model = configure_slot_model(
        slot_name="Thinking",
        slot_description="Used for complex reasoning and planning tasks.",
        capability="reasoning",
        step_label="5 of 8",
        normal_model_info=normal_model_info,
        normal_provider_id=provider_id,
        normal_model_id=model_id,
        collected_keys=collected_keys,
    )

    # Step 6: Critique model
    critique_provider, critique_model = configure_slot_model(
        slot_name="Critique",
        slot_description="Used for self-critique of reasoning. Falls back to Thinking model.",
        capability="reasoning",
        step_label="6 of 8",
        normal_model_info=normal_model_info,
        normal_provider_id=thinking_provider,
        normal_model_id=thinking_model,
        collected_keys=collected_keys,
    )

    # Step 7: Vision model
    vlm_provider, vlm_model = configure_slot_model(
        slot_name="Vision",
        slot_description="Used for image and screenshot analysis.",
        capability="vision",
        step_label="7 of 8",
        normal_model_info=normal_model_info,
        normal_provider_id=provider_id,
        normal_model_id=model_id,
        collected_keys=collected_keys,
    )

    # Step 8: Summary + save
    config = {
        "model_provider": provider_id,
        "model": model_id,
        "api_key": api_key,
        "auto_save_interval": 5,
        "model_thinking_provider": thinking_provider,
        "model_thinking": thinking_model,
        "model_critique_provider": critique_provider,
        "model_critique": critique_model,
        "model_vlm_provider": vlm_provider,
        "model_vlm": vlm_model,
    }

    show_config_summary(config, collected_keys)

    if not Confirm.ask(f"\n[{WARNING}]Save configuration?[/{WARNING}]", default=True):
        console.print(f"\n[{WARNING}]Setup cancelled[/{WARNING}]")
        return False

    if save_config(config):
        console.print()
        console.print(
            f"[bold {SUCCESS}]{SUCCESS}[/bold {SUCCESS}] "
            f"Configuration saved to ~/{APP_DIR_NAME}/settings.json"
        )
        console.print(f"[bold {SUCCESS}]{SUCCESS}[/bold {SUCCESS}] All set! Starting OpenDev...")
        console.print()
        return True

    return False


def configure_slot_model(
    *,
    slot_name: str,
    slot_description: str,
    capability: str,
    step_label: str,
    normal_model_info,
    normal_provider_id: str,
    normal_model_id: str,
    collected_keys: dict[str, str],
) -> tuple[str, str]:
    """Configure a model slot (thinking, critique, or vision).

    Args:
        slot_name: Display name for the slot ("Thinking", "Critique", or "Vision").
        slot_description: Help text shown in the info panel.
        capability: Capability to check on normal model ("reasoning" or "vision").
        step_label: Step indicator like "5 of 8".
        normal_model_info: ModelInfo of the selected normal model (or None).
        normal_provider_id: Provider ID of the normal model.
        normal_model_id: Model ID of the normal model.
        collected_keys: Dict of provider_id -> api_key, mutated in-place.

    Returns:
        (provider_id, model_id) — always returns a valid pair.
    """
    model_name = normal_model_info.name if normal_model_info else "your model"

    console.print()
    console.print(
        Panel(
            slot_description,
            title=f"{slot_name} Model ── Step {step_label}",
            border_style="cyan",
        )
    )

    # Build 2-item menu
    menu_items = [
        (
            "use_normal",
            f"Use {model_name}",
            "Same model, no extra setup needed",
        ),
        (
            "choose_manually",
            "Choose manually",
            "Select a different provider and model",
        ),
    ]

    menu = InteractiveMenu(
        items=menu_items,
        title=f"Select {slot_name} Model",
        window_size=2,
    )
    choice = menu.show()

    # "use_normal" or Esc → safe default (same as normal)
    if choice != "choose_manually":
        return normal_provider_id, normal_model_id

    # "choose_manually" → provider/model selection flow
    slot_provider_id = select_provider()
    if not slot_provider_id:
        return normal_provider_id, normal_model_id

    slot_provider_config = get_provider_config(slot_provider_id)
    if not slot_provider_config:
        console.print(f"[{ERROR}]Error: Provider '{slot_provider_id}' not found[/{ERROR}]")
        return normal_provider_id, normal_model_id

    # Collect API key if not already collected for this provider
    if slot_provider_id not in collected_keys:
        slot_api_key = get_api_key(slot_provider_id, slot_provider_config)
        if not slot_api_key:
            return normal_provider_id, normal_model_id
        # Optional validation
        if Confirm.ask(f"\n[{WARNING}]Validate API key?[/{WARNING}]", default=True):
            if not validate_key(slot_provider_id, slot_api_key):
                console.print(f"[{WARNING}]Continuing without validation.[/{WARNING}]")
        collected_keys[slot_provider_id] = slot_api_key
    else:
        console.print(
            f"[{SUCCESS}]{SUCCESS}[/{SUCCESS}] "
            f"Using previously collected API key for {slot_provider_config['name']}"
        )

    slot_model_id = select_model(slot_provider_id, slot_provider_config)
    if not slot_model_id:
        return normal_provider_id, normal_model_id
    return slot_provider_id, slot_model_id


def show_config_summary(config: dict, collected_keys: dict[str, str]) -> None:
    """Display a summary panel of the configuration before saving."""
    from swecli.config import get_model_registry

    registry = get_model_registry()

    # Resolve display names
    def _model_display(provider_id: str, model_id: str) -> str:
        provider = registry.get_provider(provider_id)
        provider_name = provider.name if provider else provider_id
        result = registry.find_model_by_id(model_id)
        model_name = result[2].name if result else model_id
        return f"{provider_name} / {model_name}"

    normal_display = _model_display(config["model_provider"], config["model"])

    thinking_same = (
        config.get("model_thinking") == config["model"]
        and config.get("model_thinking_provider") == config["model_provider"]
    )
    thinking_display = (
        "(same as Normal)"
        if thinking_same or not config.get("model_thinking")
        else _model_display(config["model_thinking_provider"], config["model_thinking"])
    )

    critique_same = (
        config.get("model_critique") == config.get("model_thinking")
        and config.get("model_critique_provider") == config.get("model_thinking_provider")
    )
    critique_display = (
        "(same as Thinking)"
        if critique_same or not config.get("model_critique")
        else _model_display(config["model_critique_provider"], config["model_critique"])
    )

    vlm_same = (
        config.get("model_vlm") == config["model"]
        and config.get("model_vlm_provider") == config["model_provider"]
    )
    vlm_display = (
        "(same as Normal)"
        if vlm_same or not config.get("model_vlm")
        else _model_display(config["model_vlm_provider"], config["model_vlm"])
    )

    # Build API key status lines
    key_lines = []
    seen_providers: set[str] = set()
    for provider_id in collected_keys:
        if provider_id in seen_providers:
            continue
        seen_providers.add(provider_id)
        provider = registry.get_provider(provider_id)
        env_var = provider.api_key_env if provider else f"{provider_id.upper()}_API_KEY"
        env_set = bool(os.getenv(env_var))
        status = f"[bold {SUCCESS}]{SUCCESS}[/bold {SUCCESS}]" if env_set else "set"
        key_lines.append(f"  ${env_var} {status}")

    keys_text = "\n".join(key_lines) if key_lines else "  (none)"

    table = Table(show_header=False, show_edge=True, border_style="cyan", padding=(0, 2))
    table.add_column("Label", style="dim", width=12)
    table.add_column("Value")

    table.add_row("Normal:", normal_display)
    table.add_row("Thinking:", thinking_display)
    table.add_row("Critique:", critique_display)
    table.add_row("Vision:", vlm_display)
    table.add_row("", "")
    table.add_row("API Keys:", keys_text)

    console.print()
    console.print(Panel(table, title="Configuration Summary", border_style="cyan"))


def select_provider() -> Optional[str]:
    """Display provider selection menu and get user choice with arrow key navigation."""
    choices = get_provider_choices()

    console.print()
    menu = InteractiveMenu(
        items=choices,
        title="Select AI Provider",
        window_size=9,
    )

    provider_id = menu.show()

    if provider_id:
        # Find the provider name for confirmation message
        provider_name = next((name for pid, name, _ in choices if pid == provider_id), provider_id)
        console.print(f"\n[{SUCCESS}]{SUCCESS}[/{SUCCESS}] Selected: {provider_name}")
        return provider_id

    console.print(f"\n[{WARNING}]Provider selection cancelled[/{WARNING}]")
    return None


def get_api_key(provider_id: str, provider_config: dict) -> Optional[str]:
    """Get API key from user input or environment variable."""
    env_var = provider_config["env_var"]
    env_key = os.getenv(env_var)

    console.print()
    if env_key:
        use_env = Confirm.ask(
            f"[{WARNING}]Found ${env_var} in environment. Use it?[/{WARNING}]",
            default=True,
        )
        if use_env:
            console.print(f"[{SUCCESS}]{SUCCESS}[/{SUCCESS}] Using API key from environment")
            return env_key

    # Prompt for manual entry
    console.print(f"\n[{WARNING}]Enter your {provider_config['name']} API key:[/{WARNING}]")
    console.print(f"[dim](or press Enter to use ${env_var})[/dim]")

    api_key = Prompt.ask("API Key", password=True)

    if not api_key:
        if env_key:
            console.print(f"[{SUCCESS}]{SUCCESS}[/{SUCCESS}] Using ${env_var}")
            return env_key
        console.print(f"[{ERROR}]![/{ERROR}] No API key provided")
        return None

    console.print(f"[{SUCCESS}]{SUCCESS}[/{SUCCESS}] API key received")
    return api_key


def validate_key(provider_id: str, api_key: str) -> bool:
    """Validate the API key with the provider."""
    console.print(f"\n[{WARNING}]Validating API key...[/{WARNING}]", end="")

    success, error = validate_api_key(provider_id, api_key)

    if success:
        console.print(f" [bold {SUCCESS}]{SUCCESS} Valid![/bold {SUCCESS}]")
        return True
    else:
        console.print(f" [bold {ERROR}]! Failed[/bold {ERROR}]")
        console.print(f"[{ERROR}]Error: {error}[/{ERROR}]")
        return False


def select_model(provider_id: str, provider_config: dict) -> Optional[str]:
    """Display model selection menu and get user choice with arrow key navigation."""
    models = get_provider_models(provider_id)

    # Convert models to menu format and add custom option
    model_choices = [(model["id"], model["name"], model["description"]) for model in models]
    model_choices.append(("__custom__", "Custom Model", "Enter a custom model ID"))

    console.print()
    menu = InteractiveMenu(
        items=model_choices,
        title=f"Select Model for {provider_config['name']}",
        window_size=9,
    )

    model_id = menu.show()

    if not model_id:
        console.print(f"\n[{WARNING}]Model selection cancelled[/{WARNING}]")
        return None

    # Handle custom model input
    if model_id == "__custom__":
        console.print()
        custom_id = Prompt.ask(f"[{WARNING}]Enter custom model ID[/{WARNING}]")
        if custom_id:
            console.print(f"[{SUCCESS}]{SUCCESS}[/{SUCCESS}] Custom model: {custom_id}")
            return custom_id
        console.print(f"[{WARNING}]No custom model ID provided[/{WARNING}]")
        return None

    # Find the model name for confirmation message
    model_name = next((name for mid, name, _ in model_choices if mid == model_id), model_id)
    console.print(f"\n[{SUCCESS}]{SUCCESS}[/{SUCCESS}] Selected: {model_name}")
    return model_id


def save_config(config: dict) -> bool:
    """Save configuration to settings.json."""
    try:
        paths = get_paths()
        paths.global_dir.mkdir(parents=True, exist_ok=True)

        config_file = paths.global_settings
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)

        return True
    except Exception as e:
        console.print(f"[{ERROR}]! Failed to save configuration: {e}[/{ERROR}]")
        return False


def config_exists() -> bool:
    """Check if configuration file exists."""
    return get_paths().global_settings.exists()
