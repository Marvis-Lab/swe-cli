"""Interactive setup wizard for first-time configuration."""

import json
import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from .providers import get_provider_config, get_provider_choices, get_provider_models
from .validator import validate_api_key
from .interactive_menu import InteractiveMenu


console = Console()


def run_setup_wizard() -> bool:
    """Run the interactive setup wizard.

    Returns:
        True if setup completed successfully, False otherwise
    """
    console.print()
    console.print(
        Panel(
            "[bold cyan]Welcome to SWE-CLI! 🚀[/bold cyan]\n\n"
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
        console.print(f"[red]Error: Provider '{provider_id}' not found[/red]")
        return False

    # Step 2: Get API key
    api_key = get_api_key(provider_id, provider_config)
    if not api_key:
        return False

    # Step 3: Validate API key (optional)
    if Confirm.ask("\n[yellow]Validate API key?[/yellow]", default=True):
        if not validate_key(provider_id, api_key):
            console.print(
                "[yellow]⚠ Continuing without validation. "
                "You may encounter errors if the key is invalid.[/yellow]"
            )

    # Step 4: Select model
    model_id = select_model(provider_id, provider_config)
    if not model_id:
        return False

    # Step 5: Advanced settings (optional)
    advanced = {}
    if Confirm.ask("\n[yellow]Configure advanced settings?[/yellow]", default=False):
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
        console.print("[bold green]✓[/bold green] Configuration saved to ~/.swecli/settings.json")
        console.print("[bold green]✓[/bold green] All set! Starting SWE-CLI...")
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
        console.print(f"\n[green]✓[/green] Selected: {provider_name}")
        return provider_id

    console.print("\n[yellow]Provider selection cancelled[/yellow]")
    return None


def get_api_key(provider_id: str, provider_config: dict) -> Optional[str]:
    """Get API key from user input or environment variable."""
    env_var = provider_config["env_var"]
    env_key = os.getenv(env_var)

    console.print()
    if env_key:
        use_env = Confirm.ask(
            f"[yellow]Found ${env_var} in environment. Use it?[/yellow]",
            default=True,
        )
        if use_env:
            console.print("[green]✓[/green] Using API key from environment")
            return env_key

    # Prompt for manual entry
    console.print(f"\n[yellow]Enter your {provider_config['name']} API key:[/yellow]")
    console.print(f"[dim](or press Enter to use ${env_var})[/dim]")

    api_key = Prompt.ask("API Key", password=True)

    if not api_key:
        if env_key:
            console.print(f"[green]✓[/green] Using ${env_var}")
            return env_key
        console.print("[red]✗[/red] No API key provided")
        return None

    console.print("[green]✓[/green] API key received")
    return api_key


def validate_key(provider_id: str, api_key: str) -> bool:
    """Validate the API key with the provider."""
    console.print("\n[yellow]Validating API key...[/yellow]", end="")

    success, error = validate_api_key(provider_id, api_key)

    if success:
        console.print(" [bold green]✓ Valid![/bold green]")
        return True
    else:
        console.print(f" [bold red]✗ Failed[/bold red]")
        console.print(f"[red]Error: {error}[/red]")
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
        console.print("\n[yellow]Model selection cancelled[/yellow]")
        return None

    # Handle custom model input
    if model_id == "__custom__":
        console.print()
        custom_id = Prompt.ask("[yellow]Enter custom model ID[/yellow]")
        if custom_id:
            console.print(f"[green]✓[/green] Custom model: {custom_id}")
            return custom_id
        console.print("[yellow]No custom model ID provided[/yellow]")
        return None

    # Find the model name for confirmation message
    model_name = next((name for mid, name, _ in model_choices if mid == model_id), model_id)
    console.print(f"\n[green]✓[/green] Selected: {model_name}")
    return model_id


def configure_advanced_settings() -> dict:
    """Configure advanced settings interactively."""
    settings = {}

    console.print("\n[bold cyan]Advanced Settings[/bold cyan]")

    # Max tokens
    max_tokens = Prompt.ask(
        "[yellow]Max tokens per response[/yellow]",
        default="16384",
    )
    try:
        settings["max_tokens"] = int(max_tokens)
    except ValueError:
        settings["max_tokens"] = 16384

    # Temperature
    temperature = Prompt.ask(
        "[yellow]Temperature (0.0-2.0)[/yellow]",
        default="0.7",
    )
    try:
        settings["temperature"] = float(temperature)
    except ValueError:
        settings["temperature"] = 0.7

    # Enable bash
    settings["enable_bash"] = Confirm.ask(
        "[yellow]Enable bash command execution?[/yellow]",
        default=True,
    )

    return settings


def save_config(config: dict) -> bool:
    """Save configuration to settings.json."""
    try:
        config_dir = Path.home() / ".swecli"
        config_dir.mkdir(parents=True, exist_ok=True)

        config_file = config_dir / "settings.json"
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)

        return True
    except Exception as e:
        console.print(f"[red]✗ Failed to save configuration: {e}[/red]")
        return False


def config_exists() -> bool:
    """Check if configuration file exists."""
    config_file = Path.home() / ".swecli" / "settings.json"
    return config_file.exists()
