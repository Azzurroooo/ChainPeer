import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.services import ContextBudget, ContextEstimator


def test_context_estimator_counts_chars_and_tokens() -> None:
    estimator = ContextEstimator(ContextBudget(max_input_tokens=100, reserve_output_tokens=20, soft_limit_tokens=15, hard_limit_tokens=20))
    messages = [
        {"role": "system", "content": "abcd"},
        {"role": "user", "content": "efghijkl"},
    ]

    estimate = estimator.estimate_messages(messages)

    if estimate.message_count != 2:
        raise AssertionError(f"Unexpected message count: {estimate}")
    if estimate.estimated_chars <= 0:
        raise AssertionError(f"Expected chars > 0, got: {estimate}")
    if estimate.estimated_input_tokens != ((estimate.estimated_chars + 3) // 4):
        raise AssertionError(f"Unexpected token estimate: {estimate}")


def test_context_estimator_limit_flags() -> None:
    estimator = ContextEstimator(ContextBudget(max_input_tokens=100, reserve_output_tokens=20, soft_limit_tokens=10, hard_limit_tokens=12))
    messages = [{"role": "user", "content": "x" * 60}]

    estimate = estimator.estimate_messages(messages)

    if estimate.over_soft_limit is not True:
        raise AssertionError(f"Expected over soft limit, got: {estimate}")
    if estimate.over_hard_limit is not True:
        raise AssertionError(f"Expected over hard limit, got: {estimate}")


def main() -> int:
    test_context_estimator_counts_chars_and_tokens()
    test_context_estimator_limit_flags()
    print("ContextEstimator tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
