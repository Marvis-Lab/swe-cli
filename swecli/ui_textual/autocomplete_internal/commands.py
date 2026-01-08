"""Slash command definitions and registry."""

from typing import List


class SlashCommand:
    """Represents a slash command."""

    def __init__(self, name: str, description: str):
        """Initialize slash command.

        Args:
            name: Command name (without /)
            description: Command description
        """
        self.name = name
        self.description = description


class CommandRegistry:
    """Registry for slash commands."""

    def __init__(self):
        """Initialize command registry."""
        self._commands: List[SlashCommand] = []

    def register(self, command: SlashCommand) -> None:
        """Register a new command.

        Args:
            command: Command to register
        """
        self._commands.append(command)

    def get_commands(self) -> List[SlashCommand]:
        """Get all registered commands.

        Returns:
            List of all commands
        """
        return self._commands.copy()

    def find_matching(self, query: str) -> List[SlashCommand]:
        """Find commands matching query.

        Args:
            query: Search query

        Returns:
            List of matching commands
        """
        query_lower = query.lower()
        return [cmd for cmd in self._commands if cmd.name.startswith(query_lower)]


# Built-in slash commands registry
BUILTIN_COMMANDS = CommandRegistry()

# Session management commands
BUILTIN_COMMANDS.register(SlashCommand("help", "show available commands and help"))
BUILTIN_COMMANDS.register(SlashCommand("exit", "exit SWE-CLI"))
BUILTIN_COMMANDS.register(SlashCommand("quit", "exit SWE-CLI (alias for /exit)"))
BUILTIN_COMMANDS.register(SlashCommand("clear", "clear current session and start fresh"))
BUILTIN_COMMANDS.register(SlashCommand("history", "show command history"))
BUILTIN_COMMANDS.register(SlashCommand("sessions", "list all saved sessions"))
BUILTIN_COMMANDS.register(SlashCommand("resume", "resume a previous session"))
BUILTIN_COMMANDS.register(SlashCommand("models", "interactive model/provider selector"))
BUILTIN_COMMANDS.register(SlashCommand("changes", "show files changed in the current session"))
BUILTIN_COMMANDS.register(SlashCommand("changed-files", "show files changed in the current session"))

# Execution commands
BUILTIN_COMMANDS.register(SlashCommand("run", "run a bash command"))
BUILTIN_COMMANDS.register(SlashCommand("mode", "switch between NORMAL and PLAN mode"))

# Advanced commands
BUILTIN_COMMANDS.register(SlashCommand("init", "analyze codebase and generate AGENTS.md"))
BUILTIN_COMMANDS.register(SlashCommand("mcp", "manage MCP servers and tools"))
BUILTIN_COMMANDS.register(SlashCommand("resolve-github-issue", "resolve a GitHub issue automatically"))
BUILTIN_COMMANDS.register(SlashCommand("paper2code", "convert PDF paper to code"))

# Background task management commands
BUILTIN_COMMANDS.register(SlashCommand("tasks", "list background tasks"))
BUILTIN_COMMANDS.register(SlashCommand("task", "show output from a background task (usage: /task <id>)"))
BUILTIN_COMMANDS.register(SlashCommand("kill", "kill a background task (usage: /kill <id>)"))
