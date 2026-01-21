"""Interactive setup wizard for first-time configuration."""

import json
import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table

from .providers import get_provider_config, get_provider_choices, get_provider_models
from .validator import validate_api_key
from .interactive_menu import InteractiveMenu
from swecli.core.paths import get_paths, APP_DIR_NAME
from swecli.ui_textual.style_tokens import CYAN, ERROR, SUCCESS, WARNING


console = Console()


def run_setup_wizard() -> bool:
    """Run the interactive setup wizard.

    Returns:
        True if setup completed successfully, False otherwise
    """
    console.print()
    console.print(
        Panel(
            "[bold cyan]Welcome to SWE-CLI! [/bold cyan]\n\n"
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
                f"[{WARNING}]⚠ Continuing without validation. "
                f"You may encounter errors if the key is invalid.[/{WARNING}]"
            )

    # Step 4: Select model
    model_id = select_model(provider_id, provider_config)
    if not model_id:
        return False

    # Step 5: Advanced settings (optional)
    advanced = {}
    if Confirm.ask(f"\n[{WARNING}]Configure advanced settings?[/{WARNING}]", default=False):
        advanced = configure_advanced_settings()

    # Step 6: Save configuration
    config = {
        "model_provider": provider_id,
        "model": model_id,
        "api_key": api_key,
        "max_tokens": advanced.get("max_tokens", 16384),
        "temperature": advanced.get("temperature", 0.7),
        "enable_bash": advanced.get("enable_bash", True),
        "auto_save_interval": 5,
        # max_context_tokens is auto-set from model's context_length
    }

    if save_config(config):
        console.print()
        console.print(f"[bold {SUCCESS}]✓[/bold {SUCCESS}] Configuration saved to ~/{APP_DIR_NAME}/settings.json")
        console.print(f"[bold {SUCCESS}]✓[/bold {SUCCESS}] All set! Starting SWE-CLI...")
        console.print()
        return True

    return False


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
        provider_name = next(
            (name for pid, name, _ in choices if pid == provider_id), provider_id
        )
        console.print(f"\n[{SUCCESS}]✓[/{SUCCESS}] Selected: {provider_name}")
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
            console.print(f"[{SUCCESS}]✓[/{SUCCESS}] Using API key from environment")
            return env_key

    # Prompt for manual entry
    console.print(f"\n[{WARNING}]Enter your {provider_config['name']} API key:[/{WARNING}]")
    console.print(f"[dim](or press Enter to use ${env_var})[/dim]")

    api_key = Prompt.ask("API Key", password=True)

    if not api_key:
        if env_key:
            console.print(f"[{SUCCESS}]✓[/{SUCCESS}] Using ${env_var}")
            return env_key
        console.print(f"[{ERROR}]✗[/{ERROR}] No API key provided")
        return None

    console.print(f"[{SUCCESS}]✓[/{SUCCESS}] API key received")
    return api_key


def validate_key(provider_id: str, api_key: str) -> bool:
    """Validate the API key with the provider."""
    console.print(f"\n[{WARNING}]Validating API key...[/{WARNING}]", end="")

    success, error = validate_api_key(provider_id, api_key)

    if success:
        console.print(f" [bold {SUCCESS}]✓ Valid![/bold {SUCCESS}]")
        return True
    else:
        console.print(f" [bold {ERROR}]✗ Failed[/bold {ERROR}]")
        console.print(f"[{ERROR}]Error: {error}[/{ERROR}]")
        return False


def select_model(provider_id: str, provider_config: dict) -> Optional[str]:
    """Display model selection menu and get user choice with arrow key navigation."""
    models = get_provider_models(provider_id)

    # Convert models to menu format and add custom option
    model_choices = [
        (model["id"], model["name"], model["description"]) for model in models
    ]
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
            console.print(f"[{SUCCESS}]✓[/{SUCCESS}] Custom model: {custom_id}")
            return custom_id
        console.print(f"[{WARNING}]No custom model ID provided[/{WARNING}]")
        return None

    # Find the model name for confirmation message
    model_name = next((name for mid, name, _ in model_choices if mid == model_id), model_id)
    console.print(f"\n[{SUCCESS}]✓[/{SUCCESS}] Selected: {model_name}")
    return model_id


def configure_advanced_settings() -> dict:
    """Configure advanced settings interactively."""
    settings = {}

    console.print(f"\n[bold {CYAN}]Advanced Settings[/bold {CYAN}]")

    # Max tokens
    max_tokens = Prompt.ask(
        f"[{WARNING}]Max tokens per response[/{WARNING}]",
        default="16384",
    )
    try:
        settings["max_tokens"] = int(max_tokens)
    except ValueError:
        settings["max_tokens"] = 16384

    # Temperature
    temperature = Prompt.ask(
        f"[{WARNING}]Temperature (0.0-2.0)[/{WARNING}]",
        default="0.7",
    )
    try:
        settings["temperature"] = float(temperature)
    except ValueError:
        settings["temperature"] = 0.7

    # Enable bash
    settings["enable_bash"] = Confirm.ask(
        f"[{WARNING}]Enable bash command execution?[/{WARNING}]",
        default=True,
    )

    return settings


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
        console.print(f"[{ERROR}]✗ Failed to save configuration: {e}[/{ERROR}]")
        return False


def config_exists() -> bool:
    """Check if configuration file exists."""
    return get_paths().global_settings.exists()
