"""System prompts for OpenDev agents."""

from .loader import load_prompt, get_prompt_path
from .injections import get_injection

__all__ = [
    "load_prompt",
    "get_prompt_path",
    "get_injection",
]
