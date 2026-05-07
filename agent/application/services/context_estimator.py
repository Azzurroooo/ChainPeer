"""Context size estimation and budget evaluation."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass


@dataclass(slots=True)
class ContextBudget:
    hard_limit_tokens: int = 32000
    system_budget_tokens: int = 2000
    conversation_budget_tokens: int = 6000
    tool_budget_tokens: int = 20000

    @classmethod
    def default(cls) -> "ContextBudget":
        return cls()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ContextEstimate:
    message_count: int
    estimated_input_tokens: int
    estimated_chars: int
    system_tokens: int
    conversation_tokens: int
    tool_tokens: int
    over_hard_limit: bool

    def to_dict(self) -> dict:
        return asdict(self)


class ContextEstimator:
    """Estimate context size without depending on a tokenizer."""

    def __init__(self, budget: ContextBudget | None = None):
        self._budget = budget or ContextBudget.default()

    @property
    def budget(self) -> ContextBudget:
        return self._budget

    def estimate_messages(self, messages: list[dict]) -> ContextEstimate:
        system_chars = 0
        conversation_chars = 0
        tool_chars = 0
        for message in messages:
            message_chars = self._estimate_message_chars(message)
            if message.get("role") == "system":
                system_chars += message_chars
            elif message.get("role") == "tool" or bool(message.get("tool_calls")):
                tool_chars += message_chars
            else:
                conversation_chars += message_chars
        estimated_chars = system_chars + conversation_chars + tool_chars
        estimated_tokens = self._chars_to_tokens(estimated_chars)
        return ContextEstimate(
            message_count=len(messages),
            estimated_input_tokens=estimated_tokens,
            estimated_chars=estimated_chars,
            system_tokens=self._chars_to_tokens(system_chars),
            conversation_tokens=self._chars_to_tokens(conversation_chars),
            tool_tokens=self._chars_to_tokens(tool_chars),
            over_hard_limit=estimated_tokens >= self._budget.hard_limit_tokens,
        )

    def _estimate_message_chars(self, message: dict) -> int:
        try:
            payload = json.dumps(message, ensure_ascii=False)
        except TypeError:
            payload = str(message)
        return len(payload)

    def _chars_to_tokens(self, chars: int) -> int:
        if chars <= 0:
            return 0
        return int(math.ceil(chars / 4))
