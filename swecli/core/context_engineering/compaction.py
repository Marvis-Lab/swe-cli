"""Auto-compaction of conversation history when approaching context limits.

Summarizes older messages into a single compact summary while preserving
the system prompt and recent messages. This prevents 400 errors from the
API when the context window is exceeded.
"""

from __future__ import annotations

import logging
from typing import Any

from swecli.core.agents.components.api.configuration import build_temperature_param
from swecli.core.agents.prompts.loader import load_prompt
from swecli.core.context_engineering.retrieval.token_monitor import ContextTokenMonitor
from swecli.models.config import AppConfig

logger = logging.getLogger(__name__)

# Trigger compaction when token usage exceeds this fraction of the context window
COMPACTION_THRESHOLD = 0.70


class ContextCompactor:
    """Auto-compacts conversation history when approaching context limits."""

    def __init__(
        self,
        config: AppConfig,
        http_client: Any,
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._token_monitor = ContextTokenMonitor()
        self._last_token_count = 0

        # Resolve actual context window from model registry
        model_info = config.get_model_info()
        if model_info and model_info.context_length:
            self._max_context = model_info.context_length
        else:
            self._max_context = getattr(config, "max_context_tokens", 100_000)

    def should_compact(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> bool:
        """Check if conversation exceeds the compaction threshold.

        Args:
            messages: Current conversation messages (API format dicts).
            system_prompt: The system prompt text.

        Returns:
            True if total tokens exceed 70% of the model's context window.
        """
        total = self._count_message_tokens(messages, system_prompt)
        self._last_token_count = total
        return total > int(self._max_context * COMPACTION_THRESHOLD)

    @property
    def usage_pct(self) -> float:
        """Context usage as percentage of the model's full context window (0-100+)."""
        if self._max_context <= 0:
            return 0.0
        return (self._last_token_count / self._max_context) * 100

    def compact(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> list[dict[str, Any]]:
        """Compact older messages into a summary, preserving recent context.

        Strategy:
            1. Keep system prompt message (index 0).
            2. Keep last N messages intact (N = min(10, len/3)).
            3. Summarize everything between into a single user message.

        Args:
            messages: Current conversation messages (API format dicts).
            system_prompt: The system prompt text (for token counting).

        Returns:
            Compacted message list with a summary replacing old messages.
        """
        if len(messages) <= 4:
            return messages

        # Determine how many recent messages to preserve
        keep_recent = min(10, max(2, len(messages) // 3))

        # First message is often system; keep it unconditionally
        head = messages[:1]
        middle = messages[1:-keep_recent]
        tail = messages[-keep_recent:]

        if not middle:
            return messages

        summary_text = self._summarize(middle)
        if not summary_text:
            # Fallback: just drop middle messages silently
            summary_text = "[Previous conversation context was compacted.]"

        summary_msg: dict[str, Any] = {
            "role": "user",
            "content": f"[CONVERSATION SUMMARY]\n{summary_text}",
        }

        compacted = head + [summary_msg] + tail

        logger.info(
            "Compacted %d messages → %d (removed %d, kept %d recent)",
            len(messages),
            len(compacted),
            len(middle),
            keep_recent,
        )

        return compacted

    def _summarize(self, messages: list[dict[str, Any]]) -> str:
        """Use the configured LLM to summarize a block of messages.

        Falls back to a simple concatenation summary if the LLM call fails.
        """
        # Build a text representation of messages to summarize
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                parts.append(f"[{role}] {content[:500]}")

        conversation_text = "\n".join(parts)

        # Prefer compact model if configured, fallback to normal
        compact_info = self._config.get_compact_model_info() if hasattr(self._config, 'get_compact_model_info') else None
        if compact_info:
            _, model_id, _ = compact_info
        else:
            model_id = getattr(self._config, "model", "gpt-4o-mini")

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": load_prompt("system/compaction_system_prompt")},
                {"role": "user", "content": conversation_text},
            ],
            "max_tokens": 1024,
            **build_temperature_param(model_id, 0.2),
        }

        try:
            result = self._http_client.post_json(payload)
            if result.success and result.response is not None:
                data = result.response.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            logger.warning("LLM summarization failed, using fallback", exc_info=True)

        # Fallback: simple concatenation truncated to ~500 chars
        return self._fallback_summary(messages)

    @staticmethod
    def _fallback_summary(messages: list[dict[str, Any]]) -> str:
        """Create a basic summary without an LLM call."""
        parts: list[str] = []
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")
            if content and role in ("user", "assistant"):
                snippet = content[:200]
                parts.append(f"- [{role}] {snippet}")
                total += len(snippet)
                if total > 2000:
                    parts.append(f"... ({len(messages) - len(parts)} more messages)")
                    break
        return "\n".join(parts)

    def _count_message_tokens(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> int:
        """Estimate total tokens across all messages and system prompt."""
        total = self._token_monitor.count_tokens(system_prompt)
        for msg in messages:
            content = msg.get("content", "")
            if content:
                total += self._token_monitor.count_tokens(content)
            # Count tool call arguments if present
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                total += self._token_monitor.count_tokens(func.get("name", ""))
                total += self._token_monitor.count_tokens(func.get("arguments", ""))
        return total
