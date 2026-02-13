"""Init subagent for codebase analysis and OPENDEV.md generation."""

from swecli.core.agents.prompts import load_prompt
from swecli.core.agents.subagents.specs import SubAgentSpec

# Load the init system prompt from template file
try:
    INIT_SYSTEM_PROMPT = load_prompt("init_system_prompt")
except Exception:
    INIT_SYSTEM_PROMPT = "Analyze codebase and generate OPENDEV.md"

INIT_SUBAGENT = SubAgentSpec(
    name="Init",
    description=(
        "Thoroughly explores a codebase to understand its structure, architecture, "
        "build systems, test setup, and conventions. Generates a comprehensive OPENDEV.md file. "
        "USE FOR: /init command, codebase documentation generation."
    ),
    system_prompt=INIT_SYSTEM_PROMPT,
    tools=["read_file", "search", "list_files", "write_file", "run_command"],
)
