"""Shared styling tokens for Textual UI surfaces."""

# =============================================================================
# Colors - All UI colors should be defined here for consistency
# =============================================================================

# Core semantic colors
PRIMARY = "#d0d4dc"
ACCENT = "#82a0ff"
SUBTLE = "#9aa0ac"
ERROR = "#ff5c57"
WARNING = "#ffb347"
SUCCESS = "#6ad18f"
GREY = "#7a7e86"
PANEL_BORDER = "#3a3f4b"

# Blues
BLUE_LIGHT = "#9ccffd"      # Headers, subtitles
BLUE_BRIGHT = "#4a9eff"     # Repo display, spinner text
BLUE_PATH = "#58a6ff"       # File paths in terminal
BLUE_BG_ACTIVE = "#1f2d3a"  # Active row background
BLUE_TASK = "#2596be"       # Background task indicator

# Greens
GREEN_BRIGHT = "#00ff00"    # Auto mode, success indicators
GREEN_LIGHT = "#89d185"     # Plan mode indicator
GREEN_PROMPT = "#7ee787"    # Terminal prompt ($)

# Oranges
ORANGE = "#ff8c00"          # Normal mode indicator
ORANGE_CAUTION = "#ffa500"  # Manual autonomy

# Cyans
CYAN = "#00bfff"            # Semi-auto mode
CYAN_VISION = "#00CED1"     # Vision model indicator

# Other
GOLD = "#FFD700"            # Thinking model indicator

# Thinking mode
THINKING = "#5a5e66"        # Darker gray for thinking content
THINKING_ICON = "⟡"         # Concave diamond - thinking prefix icon

# Icons/prefixes
ERROR_ICON = "✖"
WARNING_ICON = "⚠"
SUCCESS_ICON = "✓"
HINT_ICON = "›"
INLINE_ARROW = "⎿"

# Tool icons
TOOL_ICONS = {
    "write_file": "📝",
    "edit_file": "✏️",
    "read_file": "📖",
    "list_directory": "📁",
    "delete_file": "🗑️",
    "run_command": "⚡",
}

# Status icons
STATUS_ICONS = {
    "success": "✓",
    "error": "✗",
    "warning": "⚠",
    "info": "ℹ",
}

# Common helper strings
UNKNOWN_COMMAND_HINT = "Type /help for available commands"
