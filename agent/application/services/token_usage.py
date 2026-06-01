"""Provider token usage normalization helpers."""

from __future__ import annotations

from typing import Any


def extract_usage_dict(value: Any) -> dict[str, Any] | None:
    usage = getattr(value, "usage", None)
    if usage is None and isinstance(value, dict):
        usage = value.get("usage")
    if usage is None:
        usage = value
    if usage is None:
        return None
    return {
        "input_tokens": _int_attr(usage, "prompt_tokens", "input_tokens"),
        "cached_input_tokens": _nested_int_attr(usage, "prompt_tokens_details", "cached_tokens"),
        "output_tokens": _int_attr(usage, "completion_tokens", "output_tokens"),
        "reasoning_output_tokens": _nested_int_attr(
            usage,
            "completion_tokens_details",
            "reasoning_tokens",
        ),
        "total_tokens": _int_attr(usage, "total_tokens"),
    }


def normalize_sampling_usage(
    usage: Any,
    *,
    sampling_kind: str,
    context_window_tokens: int,
    effective_context_window_tokens: int,
) -> dict[str, Any] | None:
    extracted = extract_usage_dict(usage)
    if extracted is None:
        return None
    input_tokens = max(0, int(extracted.get("input_tokens") or 0))
    cached_tokens = max(0, int(extracted.get("cached_input_tokens") or 0))
    effective_window = max(1, int(effective_context_window_tokens or context_window_tokens or 1))
    cache_hit_rate = cached_tokens / input_tokens if input_tokens > 0 else 0.0
    context_usage_percent = input_tokens / effective_window
    return {
        "sampling_kind": sampling_kind,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "cache_hit_rate": cache_hit_rate,
        "output_tokens": max(0, int(extracted.get("output_tokens") or 0)),
        "reasoning_output_tokens": max(0, int(extracted.get("reasoning_output_tokens") or 0)),
        "total_tokens": max(0, int(extracted.get("total_tokens") or 0)),
        "context_window_tokens": max(1, int(context_window_tokens or effective_window)),
        "effective_context_window_tokens": effective_window,
        "context_usage_percent": context_usage_percent,
    }


def _int_attr(value: Any, *names: str) -> int:
    for name in names:
        raw = _get_attr(value, name)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return 0


def _nested_int_attr(value: Any, parent_name: str, child_name: str) -> int:
    parent = _get_attr(value, parent_name)
    if parent is None:
        return 0
    return _int_attr(parent, child_name)


def _get_attr(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
