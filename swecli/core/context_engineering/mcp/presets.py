"""MCP Server presets catalog for easy configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MCPPreset:
    """Configuration preset for an MCP server."""

    id: str
    name: str
    description: str
    # Stdio transport fields
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # HTTP/SSE transport fields
    transport: str = "stdio"  # stdio, http, sse
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    # Common fields
    required_env: list[str] = field(default_factory=list)
    docs_url: str = ""
    category: str = "general"


# Catalog of available MCP server presets
MCP_PRESETS: dict[str, MCPPreset] = {
    # GitHub - Official GitHub MCP server via HTTP remote
    "github": MCPPreset(
        id="github",
        name="GitHub",
        description="GitHub API access - issues, PRs, repos, code search, and more",
        transport="http",
        url="https://api.githubcopilot.com/mcp",
        headers={"Authorization": "Bearer ${GITHUB_TOKEN}"},
        required_env=["GITHUB_TOKEN"],
        docs_url="https://github.com/github/github-mcp-server",
        category="development",
    ),
    # Filesystem - Secure file operations
    "filesystem": MCPPreset(
        id="filesystem",
        name="Filesystem",
        description="Secure file operations on allowed directories",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem"],
        env={},
        required_env=[],
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
        category="system",
    ),
    # PostgreSQL - Database access
    "postgres": MCPPreset(
        id="postgres",
        name="PostgreSQL",
        description="Read-only PostgreSQL database access with schema inspection",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-postgres"],
        env={"POSTGRES_CONNECTION_STRING": "${POSTGRES_URL}"},
        required_env=["POSTGRES_URL"],
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/postgres",
        category="database",
    ),
    # SQLite - Lightweight database
    "sqlite": MCPPreset(
        id="sqlite",
        name="SQLite",
        description="SQLite database access for local databases",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-sqlite"],
        env={},
        required_env=[],
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite",
        category="database",
    ),
    # Memory - Knowledge graph
    "memory": MCPPreset(
        id="memory",
        name="Memory",
        description="Knowledge graph-based persistent memory for conversations",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-memory"],
        env={},
        required_env=[],
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/memory",
        category="general",
    ),
    # Fetch - Web content
    "fetch": MCPPreset(
        id="fetch",
        name="Fetch",
        description="Web content fetching with robots.txt compliance",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-fetch"],
        env={},
        required_env=[],
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/fetch",
        category="web",
    ),
    # Brave Search
    "brave-search": MCPPreset(
        id="brave-search",
        name="Brave Search",
        description="Web and local search using Brave Search API",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-brave-search"],
        env={"BRAVE_API_KEY": "${BRAVE_API_KEY}"},
        required_env=["BRAVE_API_KEY"],
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/brave-search",
        category="web",
    ),
    # Puppeteer - Browser automation
    "puppeteer": MCPPreset(
        id="puppeteer",
        name="Puppeteer",
        description="Browser automation for web scraping and testing",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-puppeteer"],
        env={},
        required_env=[],
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/puppeteer",
        category="web",
    ),
    # Slack
    "slack": MCPPreset(
        id="slack",
        name="Slack",
        description="Slack workspace integration - channels, messages, users",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        env={"SLACK_BOT_TOKEN": "${SLACK_BOT_TOKEN}", "SLACK_TEAM_ID": "${SLACK_TEAM_ID}"},
        required_env=["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/slack",
        category="communication",
    ),
    # Google Drive
    "gdrive": MCPPreset(
        id="gdrive",
        name="Google Drive",
        description="Google Drive file access and search",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-gdrive"],
        env={},
        required_env=[],
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive",
        category="storage",
    ),
    # Git
    "git": MCPPreset(
        id="git",
        name="Git",
        description="Git repository operations - status, diff, log, commit",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-git"],
        env={},
        required_env=[],
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/git",
        category="development",
    ),
    # Sequential Thinking
    "sequential-thinking": MCPPreset(
        id="sequential-thinking",
        name="Sequential Thinking",
        description="Dynamic problem-solving through structured thinking steps",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-sequential-thinking"],
        env={},
        required_env=[],
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking",
        category="reasoning",
    ),
}


def get_preset(name: str) -> Optional[MCPPreset]:
    """Get a preset by name (case-insensitive).

    Args:
        name: Preset identifier

    Returns:
        MCPPreset or None if not found
    """
    return MCP_PRESETS.get(name.lower())


def list_presets(category: Optional[str] = None) -> list[MCPPreset]:
    """List all available presets.

    Args:
        category: Optional category filter

    Returns:
        List of presets
    """
    presets = list(MCP_PRESETS.values())
    if category:
        presets = [p for p in presets if p.category == category.lower()]
    return presets


def search_presets(query: str) -> list[MCPPreset]:
    """Search presets by name or description.

    Args:
        query: Search query

    Returns:
        Matching presets
    """
    query = query.lower()
    return [
        preset
        for preset in MCP_PRESETS.values()
        if query in preset.name.lower()
        or query in preset.description.lower()
        or query in preset.id.lower()
    ]


def check_required_env(preset: MCPPreset) -> dict[str, bool]:
    """Check if required environment variables are set.

    Args:
        preset: The preset to check

    Returns:
        Dict mapping env var name to whether it's set
    """
    return {env_var: bool(os.environ.get(env_var)) for env_var in preset.required_env}


def get_env_setup_instructions(preset: MCPPreset) -> str:
    """Get setup instructions for missing environment variables.

    Args:
        preset: The preset to get instructions for

    Returns:
        Formatted instructions string
    """
    env_status = check_required_env(preset)
    missing = [var for var, is_set in env_status.items() if not is_set]

    if not missing:
        return ""

    instructions = f"## Required Environment Variables for {preset.name}\n\n"

    for var in missing:
        instructions += f"- `{var}`: Not set\n"

    instructions += "\n### How to Set\n\n"

    # Specific instructions for known variables
    var_instructions = {
        "GITHUB_TOKEN": (
            "Create a GitHub Personal Access Token:\n"
            "1. Go to https://github.com/settings/tokens\n"
            "2. Click 'Generate new token (classic)'\n"
            "3. Select required scopes (repo, read:org, etc.)\n"
            "4. Copy the token and set it:\n"
            "   ```\n"
            "   export GITHUB_TOKEN='ghp_xxxxxxxxxxxx'\n"
            "   ```"
        ),
        "POSTGRES_URL": (
            "Set your PostgreSQL connection string:\n"
            "   ```\n"
            "   export POSTGRES_URL='postgresql://user:pass@localhost:5432/dbname'\n"
            "   ```"
        ),
        "BRAVE_API_KEY": (
            "Get a Brave Search API key:\n"
            "1. Go to https://brave.com/search/api/\n"
            "2. Sign up and get your API key\n"
            "3. Set it:\n"
            "   ```\n"
            "   export BRAVE_API_KEY='your-api-key'\n"
            "   ```"
        ),
        "SLACK_BOT_TOKEN": (
            "Create a Slack App and get the Bot Token:\n"
            "1. Go to https://api.slack.com/apps\n"
            "2. Create an app and install to your workspace\n"
            "3. Copy the Bot User OAuth Token:\n"
            "   ```\n"
            "   export SLACK_BOT_TOKEN='xoxb-xxxxxxxxxxxx'\n"
            "   ```"
        ),
        "SLACK_TEAM_ID": (
            "Find your Slack Team ID:\n"
            "1. Open Slack in a browser\n"
            "2. The Team ID is in the URL: slack.com/client/TXXXXXXXX/...\n"
            "   ```\n"
            "   export SLACK_TEAM_ID='TXXXXXXXX'\n"
            "   ```"
        ),
    }

    for var in missing:
        if var in var_instructions:
            instructions += f"\n**{var}**:\n{var_instructions[var]}\n"
        else:
            instructions += f"\n**{var}**:\n   ```\n   export {var}='your-value'\n   ```\n"

    return instructions


def get_categories() -> list[str]:
    """Get all unique categories.

    Returns:
        List of category names
    """
    return sorted(set(preset.category for preset in MCP_PRESETS.values()))
