import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.services import ContextBudget, ContextEstimator


def test_context_budget_codex_defaults() -> None:
    budget = ContextBudget.default()

    if budget.resolved_context_window_tokens() != 258400:
        raise AssertionError(f"Unexpected context window: {budget.to_dict()}")
    if budget.resolved_effective_context_window_tokens() != 245480:
        raise AssertionError(f"Unexpected effective window: {budget.to_dict()}")
    if budget.resolved_auto_compact_token_limit() != 232560:
        raise AssertionError(f"Unexpected auto compact limit: {budget.to_dict()}")


def test_context_budget_total_scope_status() -> None:
    budget = ContextBudget(context_window_tokens=1000, effective_context_window_percent=95)

    under = budget.auto_compact_token_status(899)
    reached = budget.auto_compact_token_status(900)

    if under["auto_compact_token_limit_reached"] is not False:
        raise AssertionError(f"Expected under threshold, got: {under}")
    if reached["auto_compact_token_limit_reached"] is not True:
        raise AssertionError(f"Expected threshold reached, got: {reached}")


def test_context_budget_body_after_prefix_status() -> None:
    budget = ContextBudget(
        context_window_tokens=2000,
        auto_compact_token_limit=200,
        auto_compact_token_limit_scope="body_after_prefix",
    )

    under = budget.auto_compact_token_status(1100, prefill_input_tokens=950)
    reached = budget.auto_compact_token_status(1200, prefill_input_tokens=950)
    full_window = budget.auto_compact_token_status(1900, prefill_input_tokens=None)

    if under["auto_compact_token_limit_reached"] is not False:
        raise AssertionError(f"Expected body scope under threshold, got: {under}")
    if reached["auto_compact_token_limit_reached"] is not True:
        raise AssertionError(f"Expected body scope reached, got: {reached}")
    if full_window["auto_compact_token_limit_reached"] is not True:
        raise AssertionError(f"Expected effective window reached, got: {full_window}")


def test_context_estimator_counts_chars_and_tokens() -> None:
    estimator = ContextEstimator(ContextBudget(hard_limit_tokens=20))
    messages = [
        {"role": "system", "content": "abcd"},
        {"role": "user", "content": "efghijkl"},
        {"role": "assistant", "tool_calls": [{"id": "call_1"}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "tool output"},
    ]

    estimate = estimator.estimate_messages(messages)

    if estimate.message_count != 4:
        raise AssertionError(f"Unexpected message count: {estimate}")
    if estimate.estimated_chars <= 0:
        raise AssertionError(f"Expected chars > 0, got: {estimate}")
    if estimate.estimated_input_tokens <= 0:
        raise AssertionError(f"Unexpected token estimate: {estimate}")
    if estimate.system_tokens <= 0:
        raise AssertionError(f"Expected system tokens > 0, got: {estimate}")
    if estimate.conversation_tokens <= 0:
        raise AssertionError(f"Expected conversation tokens > 0, got: {estimate}")
    if estimate.tool_tokens <= 0:
        raise AssertionError(f"Expected tool tokens > 0, got: {estimate}")
    
    # Check if sum matches
    expected_total_tokens = estimate.system_tokens + estimate.conversation_tokens + estimate.tool_tokens
    if estimate.estimated_input_tokens != expected_total_tokens:
        raise AssertionError(f"Total tokens {estimate.estimated_input_tokens} != sum of parts {expected_total_tokens}")


def test_context_estimator_limit_flags() -> None:
    estimator = ContextEstimator(ContextBudget(hard_limit_tokens=12))
    messages = [{"role": "user", "content": "x" * 60}]

    estimate = estimator.estimate_messages(messages)

    if estimate.over_hard_limit is not True:
        raise AssertionError(f"Expected over hard limit, got: {estimate}")


def main() -> int:
    test_context_budget_codex_defaults()
    test_context_budget_total_scope_status()
    test_context_budget_body_after_prefix_status()
    test_context_estimator_counts_chars_and_tokens()
    test_context_estimator_limit_flags()
    print("ContextEstimator tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
