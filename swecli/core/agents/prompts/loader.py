"""Utilities for loading system prompts from configuration files."""

from pathlib import Path
from typing import Optional


_PROMPTS_DIR = Path(__file__).parent
_TEMPLATES_DIR = _PROMPTS_DIR / "templates"


def get_prompt_path(prompt_name: str) -> Path:
    """Get the path to a prompt file.

    Args:
        prompt_name: Name of the prompt (e.g., "main_system_prompt", "planner_system_prompt")

    Returns:
        Path to the prompt file in the templates directory
    """
    return _TEMPLATES_DIR / f"{prompt_name}.txt"


def load_prompt(prompt_name: str, fallback: Optional[str] = None) -> str:
    """Load a system prompt from file.

    Args:
        prompt_name: Name of the prompt file (without .txt extension)
        fallback: Optional fallback text if file doesn't exist

    Returns:
        The prompt text

    Raises:
        FileNotFoundError: If prompt file doesn't exist and no fallback provided
    """
    prompt_file = get_prompt_path(prompt_name)

    if not prompt_file.exists():
        if fallback is not None:
            return fallback
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    return prompt_file.read_text(encoding="utf-8").strip()


def save_prompt(prompt_name: str, content: str) -> None:
    """Save a prompt to file (useful for customization).

    Args:
        prompt_name: Name of the prompt file (without .txt extension)
        content: Prompt content to save
    """
    prompt_file = get_prompt_path(prompt_name)
    prompt_file.write_text(content, encoding="utf-8")
