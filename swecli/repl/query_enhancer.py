"""Query enhancement and message preparation for the REPL."""

import os
import re


class QueryEnhancer:
    """Handles query enhancement and message preparation."""

    def __init__(self, file_ops, session_manager, config, console):
        """Initialize query enhancer.

        Args:
            file_ops: File operations interface
            session_manager: Session manager for conversation history
            config: Configuration object
            console: Rich console for output
        """
        self.file_ops = file_ops
        self.session_manager = session_manager
        self.config = config
        self.console = console
        self.REFLECTION_WINDOW_SIZE = 10  # Keep in sync with QueryProcessor

    def enhance_query(self, query: str) -> str:
        """Enhance query with file contents if referenced.

        Includes safeguards against large files or binary formats (PDFs, images).

        Args:
            query: Original query

        Returns:
            Enhanced query with file contents or @ references stripped
        """
        # Safe extensions to auto-inject
        SAFE_EXTENSIONS = {
            ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", 
            ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
            ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".css", ".sh",
            ".gitignore", ".dockerignore", "Dockerfile", "Makefile"
        }
        MAX_INJECTION_SIZE = 50 * 1024  # 50KB limit for auto-injection

        # Extract all @file references BEFORE stripping @ symbols
        file_refs = re.findall(r'@([a-zA-Z0-9_./\-]+)', query)

        # Strip @ prefix so agent understands the query
        enhanced = re.sub(r'@([a-zA-Z0-9_./\-]+)', r'\1', query)

        file_contents = []
        for file_ref in file_refs:
            # 1. Check extension
            _, ext = os.path.splitext(file_ref)
            if ext and ext.lower() not in SAFE_EXTENSIONS and os.path.basename(file_ref) not in SAFE_EXTENSIONS:
                 # Skip unsafe/binary files (like .pdf)
                 continue

            try:
                content = self.file_ops.read_file(file_ref)
                
                # 2. Check size limit
                if len(content) > MAX_INJECTION_SIZE:
                    file_contents.append(f"Note: File '{file_ref}' referenced but too large to auto-inject ({len(content)} chars).")
                else:
                    file_contents.append(f"File contents of {file_ref}:\n```\n{content}\n```")
            except Exception:
                file_contents.append(f"Note: Could not read file '{file_ref}'.")

        # Inject file contents at the end of the query if any were found
        if file_contents:
            enhanced = f"{enhanced}\n\n" + "\n\n".join(file_contents)

        return enhanced

    def prepare_messages(self, query: str, enhanced_query: str, agent) -> list:
        """Prepare messages for LLM API call.

        Args:
            query: Original query
            enhanced_query: Query with file contents or @ references processed
            agent: Agent with system prompt

        Returns:
            List of API messages
        """
        session = self.session_manager.current_session
        messages: list[dict] = []

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

    @staticmethod
    def format_messages_summary(messages: list, max_preview_len: int = 60) -> str:
        """Format a summary of messages for debug display.

        Args:
            messages: List of message dictionaries
            max_preview_len: Maximum length for content preview

        Returns:
            Formatted summary string
        """
        if not messages:
            return "0 messages"

        summary_parts = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            # Handle string content
            if isinstance(content, str):
                preview = content[:max_preview_len]
                if len(content) > max_preview_len:
                    preview += "..."
            # Handle list content (for tool results, images, etc.)
            elif isinstance(content, list):
                preview = f"[{len(content)} blocks]"
            else:
                preview = str(content)[:max_preview_len]

            summary_parts.append(f"{role}: {preview}")

        return f"{len(messages)} messages: " + " | ".join(summary_parts)
