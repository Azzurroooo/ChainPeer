"""Context size estimation and budget evaluation."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass


@dataclass(slots=True)
class ContextBudget:
    max_input_tokens: int = 24000
    reserve_output_tokens: int = 4000
    soft_limit_tokens: int = 18000
    hard_limit_tokens: int = 20000

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
    over_soft_limit: bool
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
        estimated_chars = sum(self._estimate_message_chars(message) for message in messages)
        estimated_tokens = self._chars_to_tokens(estimated_chars)
        return ContextEstimate(
            message_count=len(messages),
            estimated_input_tokens=estimated_tokens,
            estimated_chars=estimated_chars,
            over_soft_limit=estimated_tokens >= self._budget.soft_limit_tokens,
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
