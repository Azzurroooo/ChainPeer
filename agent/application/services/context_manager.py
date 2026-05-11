"""Context construction service for model-facing conversation state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .context_estimator import ContextEstimator
from .conversation_summary_service import ConversationSummaryService
from .tool_context_policy import ToolContextPolicy


@dataclass(slots=True)
class ContextSnapshot:
    """Lightweight snapshot of context segments used to build model input."""

    system_message: dict | None = None
    recent_messages: list[dict] = field(default_factory=list)
    summary_messages: list[dict] = field(default_factory=list)
    tool_messages: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class ContextBuildResult:
    """Result of building messages for a model request."""

    messages: list[dict]
    stats: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict)
    snapshot: ContextSnapshot | None = None


class ContextManager:
    """Builds the model-facing message list from persisted session state."""

    def __init__(
        self,
        estimator: ContextEstimator | None = None,
        summary_service: ConversationSummaryService | None = None,
        tool_context_policy: ToolContextPolicy | None = None,
        hot_message_limit: int = 6,
        summary_step_threshold: int = 6,
    ):
        self._estimator = estimator or ContextEstimator()
        self._summary_service = summary_service or ConversationSummaryService()
        self._tool_context_policy = tool_context_policy or ToolContextPolicy()
        self._hot_message_limit = max(1, int(hot_message_limit))
        self._summary_step_threshold = max(1, int(summary_step_threshold))

    async def build_messages_async(self, session, pending_messages: list[dict] | None = None) -> ContextBuildResult:
        persisted_messages = [dict(message) for message in await session.get_messages_slice()]
        pending = [dict(message) for message in (pending_messages or [])]
        budget = self._estimator.budget
        full_messages = await self._apply_tool_context_policy_async(
            messages=persisted_messages + pending,
            session=session,
            tool_char_budget=budget.tool_budget_tokens * 4,
        )

        initial_estimate = self._estimator.estimate_messages(full_messages)
        messages = list(full_messages)
        summary_messages: list[dict] = []
        cold_compacted_message_count = 0
        summary_generated = False
        hot_message_count = min(
            self._hot_message_limit,
            len([message for message in full_messages if message.get("role") != "system"]),
        )

        if initial_estimate.conversation_tokens >= budget.conversation_budget_tokens:
            messages, summary_messages, cold_compacted_message_count, summary_generated = await self._compact_cold_conversation_async(
                messages=full_messages,
                session=session,
            )

        final_messages = [self._strip_internal_fields(message) for message in messages]
        final_estimate = self._estimator.estimate_messages(final_messages)
        
        dropped_count = 0
        while final_estimate.over_hard_limit and len(final_messages) > 2:
            messages, final_messages = self.rescue_context(messages, final_messages)
            final_estimate = self._estimator.estimate_messages(final_messages)
            dropped_count += 1
            if dropped_count > 50:
                break
                
        system_message = next((dict(message) for message in final_messages if message.get("role") == "system"), None)
        non_system_messages = [dict(message) for message in final_messages if message.get("role") != "system"]
        internal_tool_messages = [dict(message) for message in messages if message.get("role") == "tool"]
        tool_messages = [self._strip_internal_fields(message) for message in internal_tool_messages]
        snapshot = ContextSnapshot(
            system_message=system_message,
            recent_messages=non_system_messages,
            summary_messages=[dict(message) for message in summary_messages],
            tool_messages=tool_messages,
        )

        stats = {
            "message_count": len(messages),
            "persisted_message_count": len(persisted_messages),
            "pending_message_count": len(pending),
            "tool_message_count": len(tool_messages),
            "hot_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "hot"]),
            "warm_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "warm"]),
            "cold_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "cold"]),
            "summary_message_count": len(summary_messages),
            "hot_message_count": hot_message_count,
            "cold_compacted_message_count": cold_compacted_message_count,
            "estimated_input_tokens": final_estimate.estimated_input_tokens,
            "estimated_chars": final_estimate.estimated_chars,
            "system_tokens": final_estimate.system_tokens,
            "conversation_tokens": final_estimate.conversation_tokens,
            "tool_tokens": final_estimate.tool_tokens,
            "pre_compaction_estimated_input_tokens": initial_estimate.estimated_input_tokens,
            "pre_compaction_estimated_chars": initial_estimate.estimated_chars,
            "pre_compaction_system_tokens": initial_estimate.system_tokens,
            "pre_compaction_conversation_tokens": initial_estimate.conversation_tokens,
            "pre_compaction_tool_tokens": initial_estimate.tool_tokens,
            "budget": budget.to_dict(),
        }
        decisions = {
            "mode": "session_backed",
            "source": "session_queries",
            "uses_pending_overlay": bool(pending),
            "over_hard_limit": final_estimate.over_hard_limit,
            "over_conversation_budget": final_estimate.conversation_tokens >= budget.conversation_budget_tokens,
            "over_tool_budget": final_estimate.tool_tokens >= budget.tool_budget_tokens,
            "over_system_budget": final_estimate.system_tokens >= budget.system_budget_tokens,
            "compact_recommended": initial_estimate.conversation_tokens >= budget.conversation_budget_tokens,
            "compact_required": initial_estimate.over_hard_limit,
            "rolling_summary_applied": bool(summary_messages),
            "rolling_summary_generated": summary_generated,
            "hot_message_limit": self._hot_message_limit,
            "tool_policy_applied": True,
        }
        result = ContextBuildResult(messages=final_messages, stats=stats, decisions=decisions, snapshot=snapshot)
        await session.persist_context_snapshot(
            {
                "message_count": len(messages),
                "final_message_count": len(final_messages),
                "persisted_message_count": len(persisted_messages),
                "pending_message_count": len(pending),
                "tool_message_count": len(tool_messages),
                "hot_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "hot"]),
                "warm_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "warm"]),
                "cold_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "cold"]),
                "summary_message_count": len(summary_messages),
                "hot_message_count": hot_message_count,
                "cold_compacted_message_count": cold_compacted_message_count,
                "estimated_input_tokens": final_estimate.estimated_input_tokens,
                "estimated_chars": final_estimate.estimated_chars,
                "system_tokens": final_estimate.system_tokens,
                "conversation_tokens": final_estimate.conversation_tokens,
                "tool_tokens": final_estimate.tool_tokens,
                "pre_compaction_estimated_input_tokens": initial_estimate.estimated_input_tokens,
                "pre_compaction_estimated_chars": initial_estimate.estimated_chars,
                "pre_compaction_system_tokens": initial_estimate.system_tokens,
                "pre_compaction_conversation_tokens": initial_estimate.conversation_tokens,
                "pre_compaction_tool_tokens": initial_estimate.tool_tokens,
                "over_hard_limit": final_estimate.over_hard_limit,
                "budget": budget.to_dict(),
                "snapshot": asdict(snapshot),
                "decisions": decisions,
            }
        )
        return result

    def reduce_hard_limit(self, factor: float = 0.8) -> int:
        """Reduce the hard token limit by a factor and return the new value."""
        self._estimator.budget.hard_limit_tokens = int(
            self._estimator.budget.hard_limit_tokens * factor
        )
        return self._estimator.budget.hard_limit_tokens

    def rescue_context(self, internal_messages: list[dict], final_messages: list[dict]) -> tuple[list[dict], list[dict]]:
        """Surgical Context Rescue: Drops the oldest cold/tool messages instead of blindly shrinking budgets."""
        # Find oldest non-system message that isn't already dropped
        target_idx = -1
        for i, msg in enumerate(final_messages):
            if msg.get("role") != "system" and msg.get("content") != "[DROPPED FOR CONTEXT RESCUE]":
                # Do not drop the very last few hot messages
                if i < len(final_messages) - 2:
                    target_idx = i
                    break
                    
        if target_idx != -1:
            internal_messages[target_idx]["content"] = "[DROPPED FOR CONTEXT RESCUE]"
            final_messages[target_idx]["content"] = "[DROPPED FOR CONTEXT RESCUE]"
            
        return internal_messages, final_messages

    async def _apply_tool_context_policy_async(self, messages: list[dict], session, tool_char_budget: int | None = None) -> list[dict]:
        tool_call_ids = [message.get("tool_call_id") for message in messages if message.get("role") == "tool" and message.get("tool_call_id")]
        if not tool_call_ids:
            return [dict(message) for message in messages]

        tool_batches = self._collect_tool_batches(messages)
        temperatures = self._tool_context_policy.classify_temperatures(tool_batches)
        tool_records_list = await session.get_tool_records(call_ids=tool_call_ids)
        tool_records = {
            record.get("id"): dict(record)
            for record in tool_records_list
            if isinstance(record, dict) and record.get("id")
        }
        tool_summaries = await session.get_tool_summaries(call_ids=tool_call_ids)
        rendered_messages: list[dict] = []
        call_ids_in_order = self._tool_call_ids_in_order(messages)
        prioritized_call_ids = self._prioritize_tool_call_ids(call_ids_in_order, temperatures)
        remaining_tool_chars = tool_char_budget
        rendered_tool_content: dict[str, str] = {}

        for call_id in prioritized_call_ids:
            tool_record = tool_records.get(call_id)
            temperature = temperatures.get(call_id, "cold")
            summary_record = tool_summaries.get(call_id)
            if temperature in {"warm", "cold"} and tool_record and not summary_record:
                summary_record = self._tool_context_policy.build_tool_summary_record(tool_record)
                await session.persist_tool_summary(summary_record)
                tool_summaries[call_id] = summary_record
            rendered_content = self._tool_context_policy.render_tool_message(
                tool_record,
                summary_record,
                temperature,
                available_chars=remaining_tool_chars,
            )
            rendered_tool_content[call_id] = rendered_content
            if remaining_tool_chars is not None:
                remaining_tool_chars = max(0, remaining_tool_chars - len(rendered_content))

        for message in messages:
            rendered = dict(message)
            if rendered.get("role") == "tool" and rendered.get("tool_call_id"):
                call_id = rendered.get("tool_call_id")
                rendered["content"] = rendered_tool_content.get(call_id, "")
                rendered["_tool_temperature"] = temperatures.get(call_id, "cold")
            rendered_messages.append(rendered)
        return rendered_messages

    def _tool_call_ids_in_order(self, messages: list[dict]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for message in messages:
            if message.get("role") != "tool":
                continue
            call_id = message.get("tool_call_id")
            if not call_id or call_id in seen:
                continue
            ordered.append(call_id)
            seen.add(call_id)
        return ordered

    def _prioritize_tool_call_ids(self, call_ids: list[str], temperatures: dict[str, str]) -> list[str]:
        rank = {"hot": 0, "warm": 1, "cold": 2}
        position = {call_id: idx for idx, call_id in enumerate(call_ids)}
        return sorted(
            call_ids,
            key=lambda call_id: (rank.get(temperatures.get(call_id, "cold"), 2), position[call_id]),
        )

    def _collect_tool_batches(self, messages: list[dict]) -> list[list[str]]:
        batches: list[list[str]] = []
        for message in messages:
            if message.get("role") != "assistant":
                continue
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            batch = [item.get("id") for item in tool_calls if isinstance(item, dict) and item.get("id")]
            if batch:
                batches.append(batch)
        return batches

    def _strip_internal_fields(self, message: dict) -> dict:
        return {key: value for key, value in dict(message).items() if not key.startswith("_")}

    async def _compact_cold_conversation_async(self, messages: list[dict], session) -> tuple[list[dict], list[dict], int, bool]:
        hot_indices = self._hot_message_indices(messages)
        cold_indices = [
            index
            for index, message in enumerate(messages)
            if index not in hot_indices and self._is_summarizable_cold_message(message)
        ]
        if not cold_indices:
            return list(messages), [], 0, False

        cold_messages = [dict(messages[index]) for index in cold_indices]
        try:
            latest_summary = await session.get_latest_conversation_summary()
            summary_generated = False
            covered_count = 0
            if self._can_reuse_summary(latest_summary, cold_messages):
                summary = dict(latest_summary)
                covered_count = int(summary.get("source_message_count") or 0)
            else:
                summary = self._summary_service.summarize(cold_messages)
                await session.persist_conversation_summary(summary)
                summary_generated = True
                covered_count = len(cold_messages)
            summary_message = self._summary_service.render_summary_message(summary)
        except Exception:
            return list(messages), [], 0, False

        compacted_messages: list[dict] = []
        inserted_summary = False
        cold_index_set = set(cold_indices)
        
        skipped_cold_messages = 0
        
        for index, message in enumerate(messages):
            if index in cold_index_set:
                if not inserted_summary:
                    compacted_messages.append(dict(summary_message))
                    inserted_summary = True
                
                if skipped_cold_messages < covered_count:
                    skipped_cold_messages += 1
                    continue
                
                compacted_messages.append(dict(message))
                continue
            compacted_messages.append(dict(message))
            
        return compacted_messages, [dict(summary_message)], covered_count, summary_generated

    def _hot_message_indices(self, messages: list[dict]) -> set[int]:
        non_system_indices = [index for index, message in enumerate(messages) if message.get("role") != "system"]
        return set(non_system_indices[-self._hot_message_limit :])

    def _is_summarizable_cold_message(self, message: dict) -> bool:
        if message.get("role") not in {"user", "assistant"}:
            return False
        if message.get("tool_calls"):
            return False
        content = message.get("content", "")
        return isinstance(content, str) and bool(content.strip())

    def _can_reuse_summary(self, summary: dict | None, cold_messages: list[dict]) -> bool:
        if not isinstance(summary, dict):
            return False
        
        # We reuse the summary if the number of new cold messages since the last summary
        # is less than the summary_step_threshold.
        last_count = int(summary.get("source_message_count") or 0)
        current_count = len(cold_messages)
        
        # Must have at least as many messages as before (we don't reuse if history was deleted somehow)
        if current_count < last_count:
            return False
            
        return (current_count - last_count) < self._summary_step_threshold
