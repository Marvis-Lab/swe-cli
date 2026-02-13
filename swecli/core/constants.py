"""Shared constants for the core module."""

from __future__ import annotations

# Common directories to ignore during traversal
IGNORED_DIRS = {
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".nox",
    ".elixir_ls",
    "deps",
    "_build",
}
