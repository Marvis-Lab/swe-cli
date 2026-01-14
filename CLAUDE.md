# CLAUDE.md - Development Guidelines for SWE-CLI

## Testing Requirements

**IMPORTANT: When the user asks to "test", always perform proper end-to-end testing with real simulation using the OPENAI_API_KEY in the environment. Do not just run unit tests.**

Unit tests alone are not sufficient. Real end-to-end testing with actual API calls is required to properly verify changes.

### System Prompts

When simulating or testing, always use the exact system prompts defined in the main code:

- **Main System Prompt**: `swecli/core/agents/prompts/main_system_prompt.txt`
- **Planning System Prompt**: `swecli/core/agents/prompts/planner_system_prompt.txt`
- **Thinking System Prompt**: `swecli/core/agents/prompts/thinking_system_prompt.txt`

Do not create custom or modified prompts for testing. Use the actual prompts from these files to ensure realistic simulation.

### How to Test

```bash
# Ensure OPENAI_API_KEY is set in the environment
export OPENAI_API_KEY="your-key-here"

# Run the CLI application
python -m swecli

# Execute real commands that exercise the changed code paths
# Verify the behavior matches expected output
```
