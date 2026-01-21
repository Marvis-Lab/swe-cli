"""Centralized path management for SWE-CLI.

This module provides a single source of truth for all path-related constants
and helper functions. All paths in the application should be accessed through
this module rather than hardcoded strings.

Example:
    from swecli.core.paths import get_paths

    paths = get_paths()
    settings_file = paths.global_settings
    sessions_dir = paths.global_sessions_dir

    # Or with a specific working directory
    paths = get_paths(working_dir=Path.cwd())
    project_settings = paths.project_settings
"""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path
from typing import Optional

# ============================================================================
# Constants
# ============================================================================

# Directory and file names
APP_DIR_NAME = ".swecli"
MCP_CONFIG_NAME = "mcp.json"
MCP_PROJECT_CONFIG_NAME = ".mcp.json"  # Project-level uses dot prefix at root
SESSIONS_DIR_NAME = "sessions"
LOGS_DIR_NAME = "logs"
CACHE_DIR_NAME = "cache"
SKILLS_DIR_NAME = "skills"
AGENTS_DIR_NAME = "agents"
COMMANDS_DIR_NAME = "commands"
REPOS_DIR_NAME = "repos"
PLUGINS_DIR_NAME = "plugins"
MARKETPLACES_DIR_NAME = "marketplaces"
BUNDLES_DIR_NAME = "bundles"
PLUGIN_CACHE_DIR_NAME = "cache"
KNOWN_MARKETPLACES_FILE_NAME = "known_marketplaces.json"
INSTALLED_PLUGINS_FILE_NAME = "installed_plugins.json"
BUNDLES_FILE_NAME = "bundles.json"
SETTINGS_FILE_NAME = "settings.json"
AGENTS_FILE_NAME = "agents.json"
CONTEXT_FILE_NAME = "OPENCLI.md"
HISTORY_FILE_NAME = "history.txt"

# Environment variable names for overrides
ENV_SWECLI_DIR = "SWECLI_DIR"
ENV_SWECLI_SESSION_DIR = "SWECLI_SESSION_DIR"
ENV_SWECLI_LOG_DIR = "SWECLI_LOG_DIR"
ENV_SWECLI_CACHE_DIR = "SWECLI_CACHE_DIR"


# ============================================================================
# Paths Class
# ============================================================================


class Paths:
    """Centralized path management.

    Provides access to all application paths with support for:
    - Global paths (~/.swecli/...)
    - Project paths (<working_dir>/.swecli/...)
    - Environment variable overrides
    - Lazy directory creation

    Usage:
        paths = Paths()  # Uses Path.home() for global, Path.cwd() for project
        paths = Paths(working_dir=some_path)  # Specific project directory
    """

    def __init__(self, working_dir: Optional[Path] = None):
        """Initialize paths manager.

        Args:
            working_dir: Working directory for project-level paths.
                        Defaults to current working directory.
        """
        self._working_dir = working_dir or Path.cwd()

    @property
    def working_dir(self) -> Path:
        """Get the working directory."""
        return self._working_dir

    # ========================================================================
    # Global Paths (User-level, in ~/.swecli/)
    # ========================================================================

    @cached_property
    def global_dir(self) -> Path:
        """Get the global swecli directory.

        Can be overridden with SWECLI_DIR environment variable.
        Default: ~/.swecli/
        """
        env_override = os.environ.get(ENV_SWECLI_DIR)
        if env_override:
            return Path(env_override)
        return Path.home() / APP_DIR_NAME

    @cached_property
    def global_settings(self) -> Path:
        """Get global settings file path.

        Default: ~/.swecli/settings.json
        """
        return self.global_dir / SETTINGS_FILE_NAME

    @cached_property
    def global_sessions_dir(self) -> Path:
        """Get global sessions directory.

        Can be overridden with SWECLI_SESSION_DIR environment variable.
        Default: ~/.swecli/sessions/
        """
        env_override = os.environ.get(ENV_SWECLI_SESSION_DIR)
        if env_override:
            return Path(env_override)
        return self.global_dir / SESSIONS_DIR_NAME

    @cached_property
    def global_logs_dir(self) -> Path:
        """Get global logs directory.

        Can be overridden with SWECLI_LOG_DIR environment variable.
        Default: ~/.swecli/logs/
        """
        env_override = os.environ.get(ENV_SWECLI_LOG_DIR)
        if env_override:
            return Path(env_override)
        return self.global_dir / LOGS_DIR_NAME

    @cached_property
    def global_cache_dir(self) -> Path:
        """Get global cache directory.

        Can be overridden with SWECLI_CACHE_DIR environment variable.
        Default: ~/.swecli/cache/
        """
        env_override = os.environ.get(ENV_SWECLI_CACHE_DIR)
        if env_override:
            return Path(env_override)
        return self.global_dir / CACHE_DIR_NAME

    @cached_property
    def global_skills_dir(self) -> Path:
        """Get global skills directory.

        Default: ~/.swecli/skills/
        """
        return self.global_dir / SKILLS_DIR_NAME

    @cached_property
    def global_agents_dir(self) -> Path:
        """Get global agents directory.

        Default: ~/.swecli/agents/
        """
        return self.global_dir / AGENTS_DIR_NAME

    @cached_property
    def global_agents_file(self) -> Path:
        """Get global agents.json file path.

        Default: ~/.swecli/agents.json
        """
        return self.global_dir / AGENTS_FILE_NAME

    @cached_property
    def global_context_file(self) -> Path:
        """Get global context file (OPENCLI.md) path.

        Default: ~/.swecli/OPENCLI.md
        """
        return self.global_dir / CONTEXT_FILE_NAME

    @cached_property
    def global_mcp_config(self) -> Path:
        """Get global MCP configuration file path.

        Default: ~/.swecli/mcp.json
        """
        return self.global_dir / MCP_CONFIG_NAME

    @cached_property
    def global_repos_dir(self) -> Path:
        """Get global repos directory for cloned repositories.

        Default: ~/.swecli/repos/
        """
        return self.global_dir / REPOS_DIR_NAME

    @cached_property
    def global_history_file(self) -> Path:
        """Get global command history file path.

        Default: ~/.swecli/history.txt
        """
        return self.global_dir / HISTORY_FILE_NAME

    # ========================================================================
    # Plugin Paths (User-level, in ~/.swecli/plugins/)
    # ========================================================================

    @cached_property
    def global_plugins_dir(self) -> Path:
        """Get global plugins directory.

        Default: ~/.swecli/plugins/
        """
        return self.global_dir / PLUGINS_DIR_NAME

    @cached_property
    def global_marketplaces_dir(self) -> Path:
        """Get global marketplaces directory where marketplace repos are cloned.

        Default: ~/.swecli/plugins/marketplaces/
        """
        return self.global_plugins_dir / MARKETPLACES_DIR_NAME

    @cached_property
    def global_plugin_cache_dir(self) -> Path:
        """Get global plugin cache directory for installed plugins.

        Default: ~/.swecli/plugins/cache/
        """
        return self.global_plugins_dir / PLUGIN_CACHE_DIR_NAME

    @cached_property
    def known_marketplaces_file(self) -> Path:
        """Get known marketplaces registry file.

        Default: ~/.swecli/plugins/known_marketplaces.json
        """
        return self.global_plugins_dir / KNOWN_MARKETPLACES_FILE_NAME

    @cached_property
    def global_installed_plugins_file(self) -> Path:
        """Get global installed plugins registry file.

        Default: ~/.swecli/plugins/installed_plugins.json
        """
        return self.global_plugins_dir / INSTALLED_PLUGINS_FILE_NAME

    @cached_property
    def global_bundles_dir(self) -> Path:
        """Get global bundles directory for directly-installed plugin bundles.

        Default: ~/.swecli/plugins/bundles/
        """
        return self.global_plugins_dir / BUNDLES_DIR_NAME

    @cached_property
    def global_bundles_file(self) -> Path:
        """Get global bundles registry file.

        Default: ~/.swecli/plugins/bundles.json
        """
        return self.global_plugins_dir / BUNDLES_FILE_NAME

    # ========================================================================
    # Project Paths (Project-level, in <working_dir>/.swecli/)
    # ========================================================================

    @cached_property
    def project_dir(self) -> Path:
        """Get project-level swecli directory.

        Default: <working_dir>/.swecli/
        """
        return self._working_dir / APP_DIR_NAME

    @cached_property
    def project_settings(self) -> Path:
        """Get project settings file path.

        Default: <working_dir>/.swecli/settings.json
        """
        return self.project_dir / SETTINGS_FILE_NAME

    @cached_property
    def project_skills_dir(self) -> Path:
        """Get project skills directory.

        Default: <working_dir>/.swecli/skills/
        """
        return self.project_dir / SKILLS_DIR_NAME

    @cached_property
    def project_agents_dir(self) -> Path:
        """Get project agents directory.

        Default: <working_dir>/.swecli/agents/
        """
        return self.project_dir / AGENTS_DIR_NAME

    @cached_property
    def project_agents_file(self) -> Path:
        """Get project agents.json file path.

        Default: <working_dir>/.swecli/agents.json
        """
        return self.project_dir / AGENTS_FILE_NAME

    @cached_property
    def project_commands_dir(self) -> Path:
        """Get project commands directory.

        Default: <working_dir>/.swecli/commands/
        """
        return self.project_dir / COMMANDS_DIR_NAME

    @cached_property
    def project_context_file(self) -> Path:
        """Get project context file (OPENCLI.md) path.

        Default: <working_dir>/OPENCLI.md (at project root, not in .swecli)
        """
        return self._working_dir / CONTEXT_FILE_NAME

    @cached_property
    def project_mcp_config(self) -> Path:
        """Get project MCP configuration file path.

        Note: Project MCP config uses .mcp.json at project root (not in .swecli/)
        Default: <working_dir>/.mcp.json
        """
        return self._working_dir / MCP_PROJECT_CONFIG_NAME

    @cached_property
    def project_plugins_dir(self) -> Path:
        """Get project plugins directory.

        Default: <working_dir>/.swecli/plugins/
        """
        return self.project_dir / PLUGINS_DIR_NAME

    @cached_property
    def project_installed_plugins_file(self) -> Path:
        """Get project installed plugins registry file.

        Default: <working_dir>/.swecli/plugins/installed_plugins.json
        """
        return self.project_plugins_dir / INSTALLED_PLUGINS_FILE_NAME

    @cached_property
    def project_bundles_dir(self) -> Path:
        """Get project bundles directory for directly-installed plugin bundles.

        Default: <working_dir>/.swecli/plugins/bundles/
        """
        return self.project_plugins_dir / BUNDLES_DIR_NAME

    @cached_property
    def project_bundles_file(self) -> Path:
        """Get project bundles registry file.

        Default: <working_dir>/.swecli/plugins/bundles.json
        """
        return self.project_plugins_dir / BUNDLES_FILE_NAME

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def ensure_global_dirs(self) -> None:
        """Create all required global directories.

        Creates:
        - ~/.swecli/
        - ~/.swecli/sessions/
        - ~/.swecli/logs/
        - ~/.swecli/cache/
        - ~/.swecli/skills/
        - ~/.swecli/agents/
        - ~/.swecli/plugins/
        - ~/.swecli/plugins/marketplaces/
        - ~/.swecli/plugins/cache/
        - ~/.swecli/plugins/bundles/
        """
        self.global_dir.mkdir(parents=True, exist_ok=True)
        self.global_sessions_dir.mkdir(parents=True, exist_ok=True)
        self.global_logs_dir.mkdir(parents=True, exist_ok=True)
        self.global_cache_dir.mkdir(parents=True, exist_ok=True)
        self.global_skills_dir.mkdir(parents=True, exist_ok=True)
        self.global_agents_dir.mkdir(parents=True, exist_ok=True)
        self.global_plugins_dir.mkdir(parents=True, exist_ok=True)
        self.global_marketplaces_dir.mkdir(parents=True, exist_ok=True)
        self.global_plugin_cache_dir.mkdir(parents=True, exist_ok=True)
        self.global_bundles_dir.mkdir(parents=True, exist_ok=True)

    def ensure_project_dirs(self) -> None:
        """Create project directories if in a git repository.

        Only creates directories if .git exists in working directory.
        Creates:
        - <working_dir>/.swecli/commands/ (if .git exists)
        """
        if (self._working_dir / ".git").exists():
            self.project_commands_dir.mkdir(parents=True, exist_ok=True)

    def get_skill_dirs(self) -> list[Path]:
        """Get all skill directories in priority order.

        Returns directories in order:
        1. Project skills (.swecli/skills/) - highest priority
        2. User global skills (~/.swecli/skills/)
        3. Project bundle skills (.swecli/plugins/bundles/*/skills/)
        4. User bundle skills (~/.swecli/plugins/bundles/*/skills/)

        Only returns directories that exist.

        Returns:
            List of existing skill directories
        """
        dirs = []
        # Project skills (highest priority)
        if self.project_skills_dir.exists():
            dirs.append(self.project_skills_dir)
        # User global skills
        if self.global_skills_dir.exists():
            dirs.append(self.global_skills_dir)
        # Bundle skills are handled separately by PluginManager.get_plugin_skills()
        # to allow for proper source attribution
        return dirs

    def get_agents_dirs(self) -> list[Path]:
        """Get all agents directories in priority order.

        Returns directories in order: project first (highest priority), then global.
        Only returns directories that exist.

        Returns:
            List of existing agents directories
        """
        dirs = []
        if self.project_agents_dir.exists():
            dirs.append(self.project_agents_dir)
        if self.global_agents_dir.exists():
            dirs.append(self.global_agents_dir)
        return dirs

    def session_file(self, session_id: str) -> Path:
        """Get path to a specific session file.

        Args:
            session_id: Session ID

        Returns:
            Path to session JSON file
        """
        return self.global_sessions_dir / f"{session_id}.json"


# ============================================================================
# Singleton Access
# ============================================================================

_paths: Optional[Paths] = None


def get_paths(working_dir: Optional[Path] = None) -> Paths:
    """Get the global Paths instance.

    Creates a singleton instance on first call. If working_dir is provided,
    creates a new instance with that working directory.

    Args:
        working_dir: Optional working directory. If provided, creates a new
                    Paths instance with this directory (not cached as singleton).

    Returns:
        Paths instance
    """
    global _paths

    if working_dir is not None:
        # Return a new instance for specific working directory
        return Paths(working_dir)

    if _paths is None:
        _paths = Paths()

    return _paths


def set_paths(paths: Optional[Paths]) -> None:
    """Set the global Paths instance.

    Useful for testing or when needing to reset the singleton.

    Args:
        paths: Paths instance to set as global, or None to reset
    """
    global _paths
    _paths = paths


def reset_paths() -> None:
    """Reset the global Paths instance.

    Forces recreation on next get_paths() call.
    """
    global _paths
    _paths = None
