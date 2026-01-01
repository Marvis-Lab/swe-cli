"""ACE (Agent-Computer Interface) processor for handling reflection, curation, and learning."""

import os
from datetime import datetime
from typing import TYPE_CHECKING, Iterable, Optional

from swecli.core.context_engineering.memory import (
    AgentResponse,
    Reflector,
    Curator,
)

if TYPE_CHECKING:
    from swecli.models.message import ToolCall
    from swecli.core.context_engineering.history import SessionManager

class ACEProcessor:
    """Handles Agent-Computer Interface (ACE) logic for tool learning, reflection, and curation."""

    PLAYBOOK_DEBUG_PATH = "/tmp/swecli_debug/playbook_evolution.log"

    def __init__(self, session_manager: "SessionManager"):
        """Initialize ACE processor.

        Args:
            session_manager: Session manager for accessing current session and playbook
        """
        self.session_manager = session_manager

        # ACE Components - Initialize on first use (lazy loading)
        self._ace_reflector: Optional[Reflector] = None
        self._ace_curator: Optional[Curator] = None
        self._last_agent_response: Optional[AgentResponse] = None
        self._execution_count = 0

    def set_last_agent_response(self, response: "AgentResponse"):
        """Set the last agent response for reflection.

        Args:
            response: The agent response object
        """
        self._last_agent_response = response

    def _init_ace_components(self, agent):
        """Initialize ACE components lazily on first use.

        Args:
            agent: Agent with LLM client
        """
        if self._ace_reflector is None:
            # Initialize ACE roles with native implementation
            # The native components use swecli's LLM client directly
            self._ace_reflector = Reflector(agent.client)
            self._ace_curator = Curator(agent.client)

    def record_tool_learnings(
        self,
        query: str,
        tool_call_objects: Iterable["ToolCall"],
        outcome: str,
        agent,
    ) -> None:
        """Use ACE Reflector and Curator to evolve playbook from tool execution.

        This implements the full ACE workflow:
        1. Reflector analyzes what happened (LLM-powered)
        2. Curator decides playbook changes (delta operations)
        3. Apply deltas to evolve playbook

        Args:
            query: User's query
            tool_call_objects: Tool calls that were executed
            outcome: "success", "error", or "partial"
            agent: Agent with LLM client (for ACE initialization)
        """
        session = self.session_manager.current_session
        if not session:
            return

        tool_calls = list(tool_call_objects)
        if not tool_calls:
            return

        # Skip if no agent response (ACE workflow needs it)
        if not self._last_agent_response:
            return

        try:
            # Initialize ACE components if needed
            self._init_ace_components(agent)

            playbook = session.get_playbook()

            # Format tool feedback for reflector
            feedback = self._format_tool_feedback(tool_calls, outcome)

            # STEP 1: Reflect on execution using ACE Reflector
            reflection = self._ace_reflector.reflect(
                question=query,
                agent_response=self._last_agent_response,
                playbook=playbook,
                ground_truth=None,
                feedback=feedback
            )

            # STEP 2: Apply bullet tags from reflection
            for bullet_tag in reflection.bullet_tags:
                try:
                    playbook.tag_bullet(bullet_tag.id, bullet_tag.tag)
                except (ValueError, KeyError):
                    continue

            # STEP 3: Curate playbook updates using ACE Curator
            self._execution_count += 1
            curator_output = self._ace_curator.curate(
                reflection=reflection,
                playbook=playbook,
                question_context=query,
                progress=f"Query #{self._execution_count}"
            )

            # STEP 4: Apply delta operations
            bullets_before = len(playbook.bullets())
            playbook.apply_delta(curator_output.delta)
            bullets_after = len(playbook.bullets())

            # Save updated playbook
            session.update_playbook(playbook)

            # Debug logging
            if bullets_after != bullets_before or curator_output.delta.operations:
                debug_dir = os.path.dirname(self.PLAYBOOK_DEBUG_PATH)
                os.makedirs(debug_dir, exist_ok=True)
                with open(self.PLAYBOOK_DEBUG_PATH, "a", encoding="utf-8") as log:
                    timestamp = datetime.now().isoformat()
                    log.write(f"\n{'=' * 60}\n")
                    log.write(f"🧠 ACE PLAYBOOK EVOLUTION - {timestamp}\n")
                    log.write(f"{'=' * 60}\n")
                    log.write(f"Query: {query}\n")
                    log.write(f"Outcome: {outcome}\n")
                    log.write(f"Bullets: {bullets_before} -> {bullets_after}\n")
                    log.write(f"Delta Operations: {len(curator_output.delta.operations)}\n")
                    for op in curator_output.delta.operations:
                        log.write(f"  - {op.type}: {op.section} - {op.content[:80] if op.content else op.bullet_id}\n")
                    log.write(f"Reflection Key Insight: {reflection.key_insight}\n")
                    log.write(f"Curator Reasoning: {curator_output.delta.reasoning[:200]}\n")

        except Exception as e:  # pragma: no cover
            # Log error but don't break query processing
            import traceback
            debug_dir = os.path.dirname(self.PLAYBOOK_DEBUG_PATH)
            os.makedirs(debug_dir, exist_ok=True)
            with open(self.PLAYBOOK_DEBUG_PATH, "a", encoding="utf-8") as log:
                log.write(f"\n{'!' * 60}\n")
                log.write(f"❌ ACE ERROR: {str(e)}\n")
                log.write(traceback.format_exc())

    def _format_tool_feedback(self, tool_calls: list, outcome: str) -> str:
        """Format tool execution results as feedback string for ACE Reflector.

        Args:
            tool_calls: List of ToolCall objects with results
            outcome: "success", "error", or "partial"

        Returns:
            Formatted feedback string
        """
        lines = [f"Outcome: {outcome}"]
        lines.append(f"Tools executed: {len(tool_calls)}")

        if outcome == "success":
            lines.append("All tools completed successfully")
            # Add brief summary of what was done
            tool_names = [tc.name for tc in tool_calls]
            lines.append(f"Tools: {', '.join(tool_names)}")
        elif outcome == "error":
            # List errors
            errors = [f"{tc.name}: {tc.error}" for tc in tool_calls if tc.error]
            lines.append(f"Errors ({len(errors)}):")
            for error in errors[:3]:  # First 3 errors
                lines.append(f"  - {error[:200]}")
        else:  # partial
            successes = sum(1 for tc in tool_calls if not tc.error)
            lines.append(f"Partial success: {successes}/{len(tool_calls)} tools succeeded")

        return "\n".join(lines)
