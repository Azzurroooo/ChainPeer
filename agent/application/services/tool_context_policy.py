"""Tool context temperature policy for model-facing message rendering."""

from __future__ import annotations

import json


class ToolContextPolicy:
    """Render tool results with temperature-aware fidelity."""

    def __init__(self, hot_batch_limit: int = 1, warm_batch_limit: int = 4):
        self._hot_batch_limit = max(0, int(hot_batch_limit))
        self._warm_batch_limit = max(0, int(warm_batch_limit))

    def classify_temperatures(self, tool_batches: list[list[str]]) -> dict[str, str]:
        temperatures: dict[str, str] = {}
        normalized_batches: list[list[str]] = []
        seen: set[str] = set()
        for batch in tool_batches:
            normalized_batch: list[str] = []
            for call_id in batch:
                if not call_id or call_id in seen:
                    continue
                normalized_batch.append(call_id)
                seen.add(call_id)
            if normalized_batch:
                normalized_batches.append(normalized_batch)

        total_batches = len(normalized_batches)
        for index, batch in enumerate(normalized_batches):
            remaining_batches = total_batches - index
            if remaining_batches <= self._hot_batch_limit:
                temperature = "hot"
            elif remaining_batches <= self._hot_batch_limit + self._warm_batch_limit:
                temperature = "warm"
            else:
                temperature = "cold"
            for call_id in batch:
                temperatures[call_id] = temperature
        return temperatures

    def build_tool_summary_record(self, tool_record: dict) -> dict:
        warm_payload = {
            "tool": tool_record.get("name") or "",
            "ok": tool_record.get("ok"),
        }
        if tool_record.get("error_type"):
            warm_payload["error_type"] = tool_record.get("error_type")
        if tool_record.get("error_message"):
            warm_payload["error"] = self._truncate_value(tool_record.get("error_message"), 400, depth=1)

        result = tool_record.get("result")
        if isinstance(result, dict) and "data" in result:
            data = result.get("data")
        elif result is not None:
            data = result
        else:
            data = None

        if data is not None:
            warm_payload["data_summary"] = self._summarize_value(data, 240)
            warm_payload["data_excerpt"] = self._truncate_value(data, 800, depth=2)

        cold_payload = {
            "tool": tool_record.get("name") or "",
            "ok": tool_record.get("ok"),
        }
        if tool_record.get("error_type"):
            cold_payload["error_type"] = tool_record.get("error_type")
        if tool_record.get("error_message"):
            cold_payload["error"] = self._truncate_value(tool_record.get("error_message"), 240, depth=1)

        return {
            "call_id": tool_record.get("id"),
            "tool_name": tool_record.get("name") or "",
            "summary_for_resume": {
                "warm": warm_payload,
                "cold": cold_payload,
            },
            "version": "1",
        }

    def render_tool_message(self, tool_record: dict | None, summary_record: dict | None, temperature: str) -> str:
        if not tool_record:
            return ""

        if temperature == "hot":
            payload = self._high_fidelity_payload(tool_record)
        elif temperature == "warm":
            payload = self._summary_payload(tool_record, summary_record, default_limit=800)
        else:
            payload = self._summary_payload(tool_record, summary_record, default_limit=240)

        if isinstance(payload, str):
            return payload
        return json.dumps(payload, ensure_ascii=False)

    def _high_fidelity_payload(self, tool_record: dict) -> object:
        result = tool_record.get("result")
        if isinstance(result, str):
            return self._truncate_value(result, 4000, depth=1)
        return self._truncate_value(result, 4000, depth=3)

    def _summary_payload(self, tool_record: dict, summary_record: dict | None, default_limit: int) -> object:
        if isinstance(summary_record, dict):
            summary = summary_record.get("summary_for_resume")
            if summary is not None:
                if isinstance(summary, dict):
                    temperature_key = "warm" if default_limit >= 800 else "cold"
                    payload = summary.get(temperature_key)
                    if payload is not None:
                        return payload
                return summary
        result = tool_record.get("result")
        if isinstance(result, dict) and "ok" in result and "tool" in result:
            summarized = dict(result)
            if "data" in summarized:
                if default_limit >= 800:
                    summarized["data_summary"] = self._summarize_value(summarized["data"], 240)
                    summarized["data_excerpt"] = self._truncate_value(summarized.pop("data"), default_limit, depth=2)
                else:
                    summarized.pop("data", None)
            if "error" in summarized:
                summarized["error"] = self._truncate_value(summarized["error"], default_limit, depth=1)
            return summarized
        return self._truncate_value(result, default_limit, depth=2)

    def _summarize_value(self, value, limit: int) -> str:
        if isinstance(value, str):
            compact = " ".join(value.split())
        else:
            compact = json.dumps(self._truncate_value(value, limit, depth=2), ensure_ascii=False)
        if len(compact) <= limit:
            return compact
        return compact[:limit].rstrip() + "..."

    def _truncate_value(self, value, limit: int, depth: int = 2):
        if depth <= 0:
            return value
        if isinstance(value, str):
            if len(value) <= limit:
                return value
            return value[:limit] + f"...(truncated:{len(value)})"
        if isinstance(value, list):
            return [self._truncate_value(item, limit, depth - 1) for item in value]
        if isinstance(value, dict):
            return {key: self._truncate_value(item, limit, depth - 1) for key, item in value.items()}
        return value
