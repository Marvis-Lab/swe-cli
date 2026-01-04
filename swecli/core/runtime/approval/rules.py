"""Approval rules system for pattern-based command approval.

Rules are session-only (ephemeral) - they exist only for the current session
and are cleared when the session ends.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class RuleAction(Enum):
    AUTO_APPROVE = "auto_approve"
    AUTO_DENY = "auto_deny"
    REQUIRE_APPROVAL = "require_approval"
    REQUIRE_EDIT = "require_edit"


class RuleType(Enum):
    PATTERN = "pattern"
    COMMAND = "command"
    PREFIX = "prefix"
    DANGER = "danger"


@dataclass
class ApprovalRule:
    id: str
    name: str
    description: str
    rule_type: RuleType
    pattern: str
    action: RuleAction
    enabled: bool = True
    priority: int = 0
    created_at: Optional[str] = None
    modified_at: Optional[str] = None

    def matches(self, command: str) -> bool:
        if not self.enabled:
            return False

        if self.rule_type == RuleType.PATTERN:
            try:
                return bool(re.search(self.pattern, command))
            except re.error:
                return False
        if self.rule_type == RuleType.COMMAND:
            return command == self.pattern
        if self.rule_type == RuleType.PREFIX:
            # Match exact command OR command with additional args
            return command == self.pattern or command.startswith(self.pattern + " ")
        if self.rule_type == RuleType.DANGER:
            try:
                return bool(re.search(self.pattern, command))
            except re.error:
                return False
        return False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["rule_type"] = self.rule_type.value
        data["action"] = self.action.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalRule":
        data["rule_type"] = RuleType(data["rule_type"])
        data["action"] = RuleAction(data["action"])
        return cls(**data)


@dataclass
class CommandHistory:
    command: str
    approved: bool
    edited_command: Optional[str] = None
    timestamp: Optional[str] = None
    rule_matched: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CommandHistory":
        return cls(**data)


class ApprovalRulesManager:
    """Manager for approval rules and command history.

    All rules are session-only (in-memory). Each session starts fresh
    with default danger rules.
    """

    def __init__(self) -> None:
        self.rules: List[ApprovalRule] = []
        self.history: List[CommandHistory] = []
        self._initialize_default_rules()

    def _initialize_default_rules(self) -> None:
        """Initialize default danger rules for the session."""
        default_rules = [
            ApprovalRule(
                id="default_danger_rm",
                name="Dangerous rm commands",
                description="Require approval for dangerous rm commands",
                rule_type=RuleType.DANGER,
                pattern=r"rm\s+(-rf?|-fr?)\s+(/|\*|~)",
                action=RuleAction.REQUIRE_APPROVAL,
                priority=100,
                created_at=datetime.now().isoformat(),
            ),
            ApprovalRule(
                id="default_danger_chmod",
                name="Dangerous chmod 777",
                description="Require approval for chmod 777",
                rule_type=RuleType.DANGER,
                pattern=r"chmod\s+777",
                action=RuleAction.REQUIRE_APPROVAL,
                priority=100,
                created_at=datetime.now().isoformat(),
            ),
        ]

        self.rules.extend(default_rules)

    def evaluate_command(self, command: str) -> Optional[ApprovalRule]:
        enabled_rules = [r for r in self.rules if r.enabled]
        for rule in sorted(enabled_rules, key=lambda r: r.priority, reverse=True):
            if rule.matches(command):
                return rule
        return None

    def add_rule(self, rule: ApprovalRule) -> None:
        self.rules.append(rule)

    def update_rule(self, rule_id: str, **updates: Any) -> bool:
        for rule in self.rules:
            if rule.id == rule_id:
                for key, value in updates.items():
                    setattr(rule, key, value)
                rule.modified_at = datetime.now().isoformat()
                return True
        return False

    def remove_rule(self, rule_id: str) -> bool:
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.id != rule_id]
        return len(self.rules) != before

    def add_history(self, command: str, approved: bool, *, edited_command: Optional[str] = None, rule_matched: Optional[str] = None) -> None:
        entry = CommandHistory(
            command=command,
            approved=approved,
            edited_command=edited_command,
            timestamp=datetime.now().isoformat(),
            rule_matched=rule_matched,
        )
        self.history.append(entry)
