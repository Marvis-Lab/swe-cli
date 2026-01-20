"""Agent creator controller for the Textual chat app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from rich.console import RenderableType
from rich.text import Text

from swecli.ui_textual.components.agent_creator_panels import (
    create_location_panel,
    create_method_panel,
    create_identifier_input_panel,
    create_prompt_input_panel,
    create_description_input_panel,
    create_success_panel,
)

if TYPE_CHECKING:
    from swecli.ui_textual.chat_app import SWECLIChatApp


# Default template for new agents
AGENT_TEMPLATE = """---
name: {name}
description: "{description}"
model: sonnet
tools: "*"
---

{system_prompt}
"""


class AgentCreatorController:
    """Encapsulates the agent creation wizard flow rendered inside the conversation log."""

    # Wizard stages
    STAGE_LOCATION = "location"
    STAGE_METHOD = "method"
    STAGE_IDENTIFIER = "identifier"
    STAGE_PROMPT = "prompt"
    STAGE_DESCRIPTION = "description"
    STAGE_GENERATING = "generating"

    def __init__(self, app: "SWECLIChatApp") -> None:
        self.app = app
        self.state: dict[str, Any] | None = None
        self._config_manager: Any = None
        self._on_complete: Any = None

    @property
    def active(self) -> bool:
        return self.state is not None

    def set_config_manager(self, config_manager: Any) -> None:
        """Set the config manager for path resolution."""
        self._config_manager = config_manager

    def set_on_complete(self, callback: Any) -> None:
        """Set callback to invoke when wizard completes."""
        self._on_complete = callback

    async def start(self) -> None:
        """Begin the agent creation wizard flow."""
        if self.active:
            self.app.conversation.add_system_message(
                "Agent wizard already open — finish or press Esc to cancel."
            )
            self.app.refresh()
            return

        self.state = {
            "stage": self.STAGE_LOCATION,
            "selected_index": 0,
            "location": None,  # "project" or "personal"
            "method": None,  # "generate" or "manual"
            "agent_name": "",
            "system_prompt": "",
            "description": "",
            "input_value": "",
            "input_error": "",
            "panel_start": None,
        }

        # Clear input field and focus
        input_field = self.app.input_field
        input_field.load_text("")
        input_field.cursor_position = 0
        input_field.focus()

        self._render_current_panel()

    def end(self, message: str | None = None, *, clear_panel: bool = False) -> None:
        """Reset wizard state and optionally emit a message."""
        state = self.state
        if clear_panel and state:
            start = state.get("panel_start")
            if start is not None:
                self.app.conversation._truncate_from(start)
        self.state = None
        if message:
            self.app.conversation.add_system_message(message)
        self.app.refresh()

    def move(self, delta: int) -> None:
        """Handle up/down navigation in selection panels."""
        state = self.state
        if not state:
            return

        stage = state.get("stage")
        if stage == self.STAGE_LOCATION:
            # Location has 2 options (0 or 1)
            current = state.get("selected_index", 0)
            new_index = (current + delta) % 2
            state["selected_index"] = new_index
            self._render_current_panel()
        elif stage == self.STAGE_METHOD:
            # Method has 3 options (0, 1, or 2 for Back)
            current = state.get("selected_index", 0)
            new_index = (current + delta) % 3
            state["selected_index"] = new_index
            self._render_current_panel()

    def cancel(self) -> None:
        """Cancel the wizard."""
        if not self.state:
            return
        self.end("Agent creation cancelled.", clear_panel=True)

    def back(self) -> None:
        """Go back to the previous step in the wizard."""
        state = self.state
        if not state:
            return

        stage = state.get("stage")

        if stage == self.STAGE_METHOD:
            # Go back to location selection
            state["stage"] = self.STAGE_LOCATION
            state["selected_index"] = 0
            self._render_current_panel()
            return

        if stage == self.STAGE_IDENTIFIER:
            # Go back to method selection
            state["stage"] = self.STAGE_METHOD
            state["selected_index"] = 1  # Manual was selected
            state["input_value"] = ""
            state["input_error"] = ""
            self._render_current_panel()
            return

        if stage == self.STAGE_PROMPT:
            # Go back to identifier input
            state["stage"] = self.STAGE_IDENTIFIER
            state["input_value"] = state.get("agent_name", "")
            state["input_error"] = ""
            self._render_current_panel()
            return

        if stage == self.STAGE_DESCRIPTION:
            # Go back to method selection
            state["stage"] = self.STAGE_METHOD
            state["selected_index"] = 0  # Generate was selected
            state["input_value"] = ""
            state["input_error"] = ""
            self._render_current_panel()
            return

        # For STAGE_LOCATION or STAGE_GENERATING, just cancel
        if stage == self.STAGE_LOCATION:
            self.cancel()

    async def confirm(self) -> None:
        """Handle Enter key press - confirm selection or submit input."""
        state = self.state
        if not state:
            return

        stage = state.get("stage")

        if stage == self.STAGE_LOCATION:
            # Save location choice and move to method selection
            state["location"] = "project" if state.get("selected_index", 0) == 0 else "personal"
            state["stage"] = self.STAGE_METHOD
            state["selected_index"] = 0  # Reset selection for next panel
            self._render_current_panel()
            return

        if stage == self.STAGE_METHOD:
            selected = state.get("selected_index", 0)
            if selected == 2:  # Back option
                self.back()
                return
            # Save method choice and move to appropriate input stage
            state["method"] = "generate" if selected == 0 else "manual"
            if state["method"] == "generate":
                state["stage"] = self.STAGE_DESCRIPTION
            else:
                state["stage"] = self.STAGE_IDENTIFIER
            state["input_value"] = ""
            state["input_error"] = ""
            self._render_current_panel()
            return

        if stage == self.STAGE_IDENTIFIER:
            # Validate and save identifier
            name = state.get("input_value", "").strip().replace(" ", "-").lower()
            if not name:
                state["input_error"] = "Agent name is required"
                self._render_current_panel()
                return

            # Check for invalid characters
            if not all(c.isalnum() or c == "-" for c in name):
                state["input_error"] = "Use only letters, numbers, and hyphens"
                self._render_current_panel()
                return

            state["agent_name"] = name
            state["input_value"] = ""
            state["input_error"] = ""
            state["stage"] = self.STAGE_PROMPT
            self._render_current_panel()
            return

        if stage == self.STAGE_PROMPT:
            # Save system prompt and create the agent
            prompt = state.get("input_value", "").strip()
            if not prompt:
                state["input_error"] = "System prompt is required"
                self._render_current_panel()
                return

            state["system_prompt"] = prompt
            await self._create_agent_manual()
            return

        if stage == self.STAGE_DESCRIPTION:
            # Save description and generate with AI
            desc = state.get("input_value", "").strip()
            if not desc:
                state["input_error"] = "Description is required"
                self._render_current_panel()
                return

            state["description"] = desc
            # Skip STAGE_GENERATING panel render - _create_agent_generate shows spinner instead
            await self._create_agent_generate()
            return

    async def handle_input(self, raw_value: str) -> bool:
        """Handle text input submission.

        Returns True if input was consumed by the wizard.
        """
        state = self.state
        if not state:
            return False

        stage = state.get("stage")

        # Selection stages - handle number input
        if stage == self.STAGE_LOCATION:
            value = raw_value.strip()
            if value == "1":
                state["selected_index"] = 0
                await self.confirm()
                return True
            elif value == "2":
                state["selected_index"] = 1
                await self.confirm()
                return True
            return True  # Consume input even if invalid

        if stage == self.STAGE_METHOD:
            normalized = raw_value.strip().lower()
            if normalized in {"b", "back"}:
                self.back()
                return True
            if normalized == "1":
                state["selected_index"] = 0
                await self.confirm()
                return True
            elif normalized == "2":
                state["selected_index"] = 1
                await self.confirm()
                return True
            return True

        # Text input stages
        if stage in (self.STAGE_IDENTIFIER, self.STAGE_PROMPT, self.STAGE_DESCRIPTION):
            state["input_value"] = raw_value.strip()
            await self.confirm()
            return True

        return False

    def update_input_preview(self, text: str) -> None:
        """Update the panel to show current input text (live preview)."""
        state = self.state
        if not state:
            return

        stage = state.get("stage")
        if stage in (self.STAGE_IDENTIFIER, self.STAGE_PROMPT, self.STAGE_DESCRIPTION):
            state["input_value"] = text
            self._render_current_panel()

    def _render_current_panel(self) -> None:
        """Render the appropriate panel for the current stage."""
        state = self.state
        if not state:
            return

        stage = state.get("stage")
        working_dir = (
            getattr(self._config_manager, "working_dir", "") if self._config_manager else ""
        )

        if stage == self.STAGE_LOCATION:
            panel = create_location_panel(state.get("selected_index", 0), working_dir=working_dir)
        elif stage == self.STAGE_METHOD:
            panel = create_method_panel(state.get("selected_index", 0))
        elif stage == self.STAGE_IDENTIFIER:
            panel = create_identifier_input_panel(
                state.get("input_value", ""), state.get("input_error", "")
            )
        elif stage == self.STAGE_PROMPT:
            panel = create_prompt_input_panel(state.get("input_value", ""))
        elif stage == self.STAGE_DESCRIPTION:
            panel = create_description_input_panel(state.get("input_value", ""))
        else:
            # STAGE_GENERATING is handled by spinner in _create_agent_generate()
            return

        self._post_panel(panel)

    def _post_panel(self, panel: RenderableType) -> None:
        """Post Rich panel to conversation, replacing previous panel if exists."""
        state = self.state
        if state is not None:
            start = state.get("panel_start")
            conversation = self.app.conversation
            if start is None or start > len(conversation.lines):
                state["panel_start"] = len(conversation.lines)
            else:
                conversation._truncate_from(start)

        # Write Rich renderable directly
        self.app.conversation.write(panel)
        self.app.conversation.write(Text(""))
        self.app.conversation.scroll_end(animate=False)
        self.app.refresh()

    def _get_agents_dir(self) -> Path:
        """Get the appropriate agents directory based on location choice."""
        from swecli.core.paths import get_paths, APP_DIR_NAME

        state = self.state
        if not state:
            raise ValueError("No wizard state")

        if self._config_manager:
            paths = get_paths(self._config_manager.working_dir)
        else:
            paths = get_paths(None)

        if state.get("location") == "project":
            return paths.project_agents_dir
        else:
            return paths.global_agents_dir

    async def _create_agent_manual(self) -> None:
        """Create agent with manual configuration."""
        state = self.state
        if not state:
            return

        name = state.get("agent_name", "")
        system_prompt = state.get("system_prompt", "")

        try:
            agents_dir = self._get_agents_dir()
            agents_dir.mkdir(parents=True, exist_ok=True)

            agent_file = agents_dir / f"{name}.md"

            # Generate description from name
            description = f"A specialized agent for {name.replace('-', ' ')}"

            content = AGENT_TEMPLATE.format(
                name=name,
                description=description,
                system_prompt=system_prompt,
            )

            agent_file.write_text(content, encoding="utf-8")

            # Show success panel
            success_panel = create_success_panel(name, str(agent_file))
            self._post_panel(success_panel)

            # Clear state but keep panel visible
            self.state = None

            if self._on_complete:
                self._on_complete(name, str(agent_file))

        except Exception as e:
            self.end(f"Failed to create agent: {e}", clear_panel=True)

    async def _create_agent_generate(self) -> None:
        """Create agent using AI generation."""
        import asyncio

        state = self.state
        if not state:
            return

        description = state.get("description", "")

        # Clear the wizard panel before starting generation
        start = state.get("panel_start")
        if start is not None:
            self.app.conversation._truncate_from(start)

        # Get spinner service from app
        spinner_service = getattr(self.app, "spinner_service", None)
        spinner_id = None

        try:
            # Start spinner animation
            if spinner_service:
                spinner_id = spinner_service.start(
                    "Generating agent...",
                    skip_placeholder=True,
                )
                self.app.refresh()

            # Get config and create HTTP client
            if not self._config_manager:
                raise ValueError("Config manager not set")

            config = self._config_manager.get_config()

            from swecli.core.agents.components import (
                create_http_client,
                build_max_tokens_param,
                build_temperature_param,
            )

            http_client = create_http_client(config)

            # Load system prompt for agent generation
            prompt_path = (
                Path(__file__).parent.parent.parent
                / "core/agents/prompts/agent_generator_prompt.txt"
            )
            generator_system_prompt = prompt_path.read_text(encoding="utf-8")

            # Build messages
            messages = [
                {"role": "system", "content": generator_system_prompt},
                {"role": "user", "content": f"Create an agent for: {description}"},
            ]

            # Build payload (no tools needed for generation)
            payload = {
                "model": config.model,
                "messages": messages,
                **build_max_tokens_param(config.model, 4000),
                **build_temperature_param(config.model, 0.7),
            }

            # Run blocking HTTP call in background thread (non-blocking!)
            result = await asyncio.to_thread(
                http_client.post_json,
                payload,
                task_monitor=None,
            )

            if result.success and result.response and result.response.status_code == 200:
                response_data = result.response.json()
                content = response_data["choices"][0]["message"]["content"]

                # Parse the response to extract name and write the file
                name, agent_content = self._parse_generated_agent(content, description)

                agents_dir = self._get_agents_dir()
                agents_dir.mkdir(parents=True, exist_ok=True)

                agent_file = agents_dir / f"{name}.md"
                agent_file.write_text(agent_content, encoding="utf-8")

                # Stop spinner with success result
                if spinner_service and spinner_id:
                    spinner_service.stop(
                        spinner_id,
                        success=True,
                        result_message=f"Created agent: {name} at {agent_file}",
                    )

                # Clear state
                self.state = None

                if self._on_complete:
                    self._on_complete(name, str(agent_file))
            else:
                # LLM call failed
                error_msg = result.error if result.error else "Unknown error"
                if spinner_service and spinner_id:
                    spinner_service.stop(spinner_id, success=False, result_message=error_msg)
                await self._create_agent_fallback(description, error_msg)

        except Exception as e:
            if spinner_service and spinner_id:
                spinner_service.stop(spinner_id, success=False, result_message=str(e))
            self.end(f"Failed to create agent: {e}", clear_panel=True)

    def _parse_generated_agent(self, content: str, description: str) -> tuple[str, str]:
        """Parse LLM-generated agent content and extract name.

        Returns:
            Tuple of (agent_name, full_content)
        """
        import re

        content = content.strip()

        # Remove markdown code block wrapper if present
        if content.startswith("```"):
            # Find first newline after opening backticks
            first_newline = content.find("\n")
            if first_newline != -1:
                content = content[first_newline + 1 :]
            # Remove closing backticks
            if content.rstrip().endswith("```"):
                content = content.rstrip()[:-3].rstrip()

        # Extract name from YAML frontmatter
        name = "custom-agent"
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if frontmatter_match:
            frontmatter = frontmatter_match.group(1)
            name_match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
            if name_match:
                name = name_match.group(1).strip().strip('"').strip("'")

        # Clean the name to ensure it's valid
        name = "".join(c if c.isalnum() or c == "-" else "-" for c in name.lower())
        name = "-".join(filter(None, name.split("-")))[:30]  # Max 30 chars

        if not name:
            name = "custom-agent"

        return name, content

    async def _create_agent_fallback(self, description: str, error_msg: str) -> None:
        """Create agent with basic template when LLM generation fails."""
        # Extract a name from the description
        words = description.lower().split()
        name_candidates = []
        for word in words:
            if len(word) > 3 and word.isalpha():
                name_candidates.append(word)

        if name_candidates:
            name = "-".join(name_candidates[:2])
        else:
            name = "custom-agent"

        # Clean the name
        name = "".join(c if c.isalnum() or c == "-" else "-" for c in name)
        name = "-".join(filter(None, name.split("-")))[:30]

        # Generate basic system prompt
        system_prompt = f"""You are a specialized agent for the following purpose:

{description}

## Your Mission

{description}

## Guidelines

- Be thorough and provide clear explanations
- Use available tools to gather information and complete tasks
- Ask clarifying questions if requirements are unclear
- Focus on delivering high-quality results
"""

        agents_dir = self._get_agents_dir()
        agents_dir.mkdir(parents=True, exist_ok=True)

        agent_file = agents_dir / f"{name}.md"

        content = AGENT_TEMPLATE.format(
            name=name,
            description=description[:100] + "..." if len(description) > 100 else description,
            system_prompt=system_prompt,
        )

        agent_file.write_text(content, encoding="utf-8")

        # Show inline system message about fallback creation
        self.app.conversation.add_system_message(
            f"  ⎿  Created agent with basic template: {name} at {agent_file}"
        )
        self.app.refresh()

        # Clear state
        self.state = None

        if self._on_complete:
            self._on_complete(name, str(agent_file))


__all__ = ["AgentCreatorController"]
