"""Context preparer for enhancing queries and preparing messages."""

import os
import re
from typing import TYPE_CHECKING, Optional, List, Dict, Any

if TYPE_CHECKING:
    from rich.console import Console
    from swecli.core.context_engineering.history import SessionManager
    from swecli.core.context_engineering.tools.implementations import FileOperations
    from swecli.models.config import Config


class ContextPreparer:
    """Handles query enhancement and message preparation for LLM context."""

    REFLECTION_WINDOW_SIZE = 10
    MAX_ERROR_RECOVERY_ATTEMPTS = 3

    def __init__(
        self,
        console: "Console",
        session_manager: "SessionManager",
        config: "Config",
        file_ops: "FileOperations",
    ):
        """Initialize context preparer.

        Args:
            console: Rich console for output
            session_manager: Session manager for message tracking
            config: Configuration
            file_ops: File operations for query enhancement
        """
        self.console = console
        self.session_manager = session_manager
        self.config = config
        self.file_ops = file_ops

    def enhance_query(self, query: str) -> str:
        """Enhance query with file contents if referenced.

        Args:
            query: Original query

        Returns:
            Enhanced query with file contents or @ references stripped
        """
        # Handle @file references - strip @ prefix so agent understands
        # Pattern: @filename or @path/to/filename (with or without extension)
        # This makes "@app.py" become "app.py" in the query
        enhanced = re.sub(r'@([a-zA-Z0-9_./\-]+)', r'\1', query)

        # Simple heuristic: look for file references and include content
        lower_query = enhanced.lower()
        if any(keyword in lower_query for keyword in ["explain", "what does", "show me"]):
            # Try to extract file paths
            words = enhanced.split()
            for word in words:
                if any(word.endswith(ext) for ext in [".py", ".js", ".ts", ".java", ".go", ".rs"]):
                    try:
                        content = self.file_ops.read_file(word)
                        return f"{enhanced}\n\nFile contents of {word}:\n```\n{content}\n```"
                    except Exception:
                        pass

        return enhanced

    def prepare_messages(self, query: str, enhanced_query: str, agent) -> List[Dict[str, Any]]:
        """Prepare messages for LLM API call.

        Args:
            query: Original query
            enhanced_query: Query with file contents or @ references processed
            agent: Agent with system prompt

        Returns:
            List of API messages
        """
        session = self.session_manager.current_session
        messages: List[Dict[str, Any]] = []

        if session:
            messages = session.to_api_messages(window_size=self.REFLECTION_WINDOW_SIZE)
            if enhanced_query != query:
                for entry in reversed(messages):
                    if entry.get("role") == "user":
                        entry["content"] = enhanced_query
                        break
        else:
            messages = []

        system_content = agent.system_prompt
        if session:
            try:
                playbook = session.get_playbook()
                # Use ACE's as_context() method for intelligent bullet selection
                # Configuration from config.playbook section
                playbook_config = getattr(self.config, 'playbook', None)
                if playbook_config:
                    max_strategies = playbook_config.max_strategies
                    use_selection = playbook_config.use_selection
                    weights = playbook_config.scoring_weights.to_dict()
                    embedding_model = playbook_config.embedding_model
                    cache_file = playbook_config.cache_file
                    # If cache_file not specified but cache enabled, use session-based default
                    if cache_file is None and playbook_config.cache_embeddings and session:
                        swecli_dir = os.path.expanduser(self.config.swecli_dir)
                        cache_file = os.path.join(swecli_dir, "sessions", f"{session.session_id}_embeddings.json")
                else:
                    # Fallback to defaults if config not available
                    max_strategies = 30
                    use_selection = True
                    weights = None
                    embedding_model = "text-embedding-3-small"
                    cache_file = None

                playbook_context = playbook.as_context(
                    query=query,  # Enables semantic matching (Phase 2)
                    max_strategies=max_strategies,
                    use_selection=use_selection,
                    weights=weights,
                    embedding_model=embedding_model,
                    cache_file=cache_file,
                )
                if playbook_context:
                    system_content = f"{system_content.rstrip()}\n\n## Learned Strategies\n{playbook_context}"
            except Exception:  # pragma: no cover
                pass

        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": system_content})
        else:
            messages[0]["content"] = system_content

        # Debug: Log message count and estimated size
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        estimated_tokens = total_chars // 4  # Rough estimate: 4 chars per token
        if self.console and hasattr(self.console, "print"):
            if estimated_tokens > 100000:  # Warn if > 100k tokens
                self.console.print(
                    f"[yellow]⚠ Large context: {len(messages)} messages, ~{estimated_tokens:,} tokens[/yellow]"
                )

        return messages

    def should_nudge_agent(self, consecutive_reads: int, messages: List[Dict[str, Any]]) -> bool:
        """Check if agent should be nudged to conclude.

        Args:
            consecutive_reads: Number of consecutive read operations
            messages: Message history

        Returns:
            True if nudge was added
        """
        if consecutive_reads >= 5:
            # Silently nudge the agent without displaying a message
            messages.append({
                "role": "user",
                "content": "Based on what you've seen, please summarize your findings and explain what needs to be done next."
            })
            return True
        return False

    def should_attempt_error_recovery(self, messages: List[Dict[str, Any]], attempts: int) -> bool:
        """Check if we should inject a recovery prompt after tool failure.

        When the LLM returns no tool calls after a tool error, this method
        determines if we should prompt it to fix the issue and retry.

        Args:
            messages: Message history
            attempts: Number of recovery attempts already made

        Returns:
            True if recovery should be attempted
        """
        if attempts >= self.MAX_ERROR_RECOVERY_ATTEMPTS:
            return False

        # Find the most recent tool result
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                # Check if the tool failed
                if content.startswith("Error:"):
                    return True
                # Only check the most recent tool result
                break
        return False
