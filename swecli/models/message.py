"""Chat message models."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    """Message role enum."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ToolCall(BaseModel):
    """Tool call information."""

    id: str
    name: str
    parameters: dict[str, Any]
    result: Optional[Any] = None
    result_summary: Optional[str] = None  # Concise 1-2 line summary for LLM context
    timestamp: datetime = Field(default_factory=datetime.now)
    approved: bool = False
    error: Optional[str] = None
    nested_tool_calls: list["ToolCall"] = Field(default_factory=list)  # For subagent tools


class ChatMessage(BaseModel):
    """Represents a single message in the conversation."""

    role: Role
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tokens: Optional[int] = None

    # Fields for complete session persistence
    thinking_trace: Optional[str] = None  # Thinking/reasoning used for this response
    reasoning_content: Optional[str] = None  # Native model reasoning (o1/o3)
    token_usage: Optional[dict[str, Any]] = None  # Token usage stats (may contain nested dicts)

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})

    def token_estimate(self) -> int:
        """Estimate token count (rough approximation)."""
        if self.tokens:
            return self.tokens
        # Rough estimate: ~4 chars per token
        return len(self.content) // 4 + sum(len(str(tc.parameters)) // 4 for tc in self.tool_calls)
