"""Context construction service for model-facing conversation state."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.domain.skills import render_active_skill_instructions

from .context_estimator import ContextEstimator


@dataclass(slots=True)
class ContextBuildResult:
    """Result of building messages for a model request."""

    messages: list[dict]
    stats: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict)


class ContextManager:
    """Builds the model-facing message list from persisted session state."""

    def __init__(
        self,
        estimator: ContextEstimator | None = None,
        hot_message_limit: int = 6,
        skill_repository=None,
        skill_selector=None,
        plan_context_provider=None,
        skill_index_char_limit: int = 0,
        active_skill_char_limit: int = 12000,
    ):
        self._estimator = estimator or ContextEstimator()
        self._hot_message_limit = max(1, int(hot_message_limit))
        self._skill_repository = skill_repository
        self._skill_selector = skill_selector
        self._plan_context_provider = plan_context_provider
        self._active_skill_char_limit = max(0, int(active_skill_char_limit))

    async def build_messages_async(
        self,
        session,
        pending_messages: list[dict] | None = None,
        active_skill_matches: list | None = None,
        allow_rescue: bool = False,
    ) -> ContextBuildResult:
        persisted_messages = [dict(message) for message in await session.get_messages_slice()]
        pending = [dict(message) for message in (pending_messages or [])]
        budget = self._estimator.budget
        full_messages = persisted_messages + pending
        plan_messages, plan_stats, plan_decisions = self._build_plan_messages()
        skill_messages, skill_stats, skill_decisions = self._build_skill_messages(active_skill_matches)
        if skill_messages:
            full_messages = self._insert_after_first_system(full_messages, skill_messages)
        if plan_messages:
            full_messages = self._insert_before_latest_user(full_messages, plan_messages)

        messages = list(full_messages)
        hot_message_count = min(
            self._hot_message_limit,
            len([message for message in full_messages if self._is_conversation_message(message)]),
        )

        final_messages = [self._strip_internal_fields(message) for message in messages]
        final_estimate = self._estimator.estimate_messages(final_messages)
        
        dropped_count = 0
        while allow_rescue and final_estimate.over_hard_limit and len(final_messages) > 2:
            messages, final_messages = self.rescue_context(messages, final_messages)
            final_estimate = self._estimator.estimate_messages(final_messages)
            dropped_count += 1
            if dropped_count > 50:
                break

        tool_messages = [dict(message) for message in final_messages if message.get("role") == "tool"]
        compact_threshold_tokens = budget.resolved_compact_threshold_tokens()
        auto_compact_window = await self._get_auto_compact_window(session)
        auto_compact_window_prefill_tokens = auto_compact_window.get("prefill_input_tokens")
        auto_compact_status = budget.auto_compact_token_status(
            final_estimate.estimated_input_tokens,
            auto_compact_window_prefill_tokens,
        )
        context_window_tokens = budget.resolved_context_window_tokens()
        effective_context_window_tokens = budget.resolved_effective_context_window_tokens()
        context_usage_percent = final_estimate.estimated_input_tokens / max(1, effective_context_window_tokens)

        stats = {
            "message_count": len(messages),
            "persisted_message_count": len(persisted_messages),
            "pending_message_count": len(pending),
            "tool_message_count": len(tool_messages),
            "hot_message_count": hot_message_count,
            "estimated_input_tokens": final_estimate.estimated_input_tokens,
            "estimated_chars": final_estimate.estimated_chars,
            "system_tokens": final_estimate.system_tokens,
            "conversation_tokens": final_estimate.conversation_tokens,
            "tool_tokens": final_estimate.tool_tokens,
            "context_window_tokens": context_window_tokens,
            "effective_context_window_tokens": effective_context_window_tokens,
            "auto_compact_token_limit": budget.resolved_auto_compact_token_limit(),
            "context_usage_percent": context_usage_percent,
            "budget": budget.to_dict(),
            **auto_compact_status,
            **plan_stats,
            **skill_stats,
        }
        decisions = {
            "mode": "session_backed",
            "source": "session_queries",
            "uses_pending_overlay": bool(pending),
            "over_hard_limit": final_estimate.over_hard_limit,
            "over_conversation_budget": final_estimate.conversation_tokens >= budget.conversation_budget_tokens,
            "over_tool_budget": final_estimate.tool_tokens >= budget.tool_budget_tokens,
            "over_system_budget": final_estimate.system_tokens >= budget.system_budget_tokens,
            "compact_recommended": final_estimate.estimated_input_tokens >= compact_threshold_tokens,
            "compact_required": final_estimate.over_hard_limit,
            "auto_compact_token_limit_reached": auto_compact_status["auto_compact_token_limit_reached"],
            **plan_decisions,
            **skill_decisions,
        }
        return ContextBuildResult(messages=final_messages, stats=stats, decisions=decisions)

    async def _get_auto_compact_window(self, session) -> dict:
        get_window = getattr(session, "get_auto_compact_window", None)
        if callable(get_window):
            try:
                window = await get_window()
                if isinstance(window, dict):
                    return dict(window)
            except Exception:
                return {}
        return {}

    def reduce_hard_limit(self, factor: float = 0.8) -> int:
        """Reduce the hard token limit by a factor and return the new value."""
        budget = self._estimator.budget
        budget.hard_limit_tokens = int(budget.resolved_hard_limit_tokens() * factor)
        return budget.resolved_hard_limit_tokens()

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

    def _strip_internal_fields(self, message: dict) -> dict:
        return {key: value for key, value in dict(message).items() if not key.startswith("_")}

    def select_active_skills_for_turn(self, user_message: str) -> list:
        if not self._skill_repository or not self._skill_selector:
            return []
        try:
            skills = list(self._skill_repository.list_skills())
            return list(self._skill_selector.select(user_message, skills))
        except Exception:
            return []

    def _build_plan_messages(self) -> tuple[list[dict], dict, dict]:
        stats = {
            "plan_summary_chars": 0,
            "plan_open": False,
            "plan_step_count": 0,
            "plan_unfinished_step_count": 0,
        }
        decisions = {
            "plan_summary_injected": False,
            "plan_id": None,
            "plan_version": None,
            "plan_state": "none",
        }
        if not self._plan_context_provider:
            return [], stats, decisions
        try:
            return self._plan_context_provider.build_context()
        except Exception:
            decisions["plan_state"] = "error"
            return [], stats, decisions

    def _build_skill_messages(self, active_skill_matches: list | None = None) -> tuple[list[dict], dict, dict]:
        stats = {
            "skill_count": 0,
            "active_skill_count": 0,
            "skill_index_chars": 0,
            "active_skill_chars": 0,
        }
        decisions = {
            "skills_available": False,
            "active_skills": [],
            "skill_injection_applied": False,
        }
        if not self._skill_repository:
            return [], stats, decisions

        try:
            skills = list(self._skill_repository.list_skills())
        except Exception:
            return [], stats, decisions
        if not skills:
            return [], stats, decisions

        active_matches = list(active_skill_matches or [])
        messages: list[dict] = []

        active_content = ""
        if active_matches:
            active_content = render_active_skill_instructions(active_matches, self._active_skill_char_limit)
            if active_content:
                messages.append({"role": "system", "content": active_content})

        stats.update(
            {
                "skill_count": len(skills),
                "active_skill_count": len(active_matches),
                "skill_index_chars": 0,
                "active_skill_chars": len(active_content),
            }
        )
        decisions.update(
            {
                "skills_available": True,
                "active_skills": [
                    {
                        "name": match.skill.name,
                        "reason": match.reason,
                        "score": match.score,
                        "source": match.skill.source,
                        "path": match.skill.path,
                    }
                    for match in active_matches
                ],
                "skill_injection_applied": bool(messages),
            }
        )
        return messages, stats, decisions

    def _insert_after_first_system(self, messages: list[dict], extra_messages: list[dict]) -> list[dict]:
        if not extra_messages:
            return list(messages)
        result: list[dict] = []
        inserted = False
        for message in messages:
            result.append(dict(message))
            if not inserted and message.get("role") == "system":
                result.extend(dict(item) for item in extra_messages)
                inserted = True
        if not inserted:
            result = [dict(item) for item in extra_messages] + result
        return result

    def _insert_before_latest_user(self, messages: list[dict], extra_messages: list[dict]) -> list[dict]:
        if not extra_messages:
            return list(messages)
        result = [dict(message) for message in messages]
        insert_at = None
        for index in range(len(result) - 1, -1, -1):
            if result[index].get("role") == "user":
                insert_at = index
                break
        rendered_extra = [dict(item) for item in extra_messages]
        if insert_at is None:
            return result + rendered_extra
        return result[:insert_at] + rendered_extra + result[insert_at:]

    def _is_conversation_message(self, message: dict) -> bool:
        if message.get("role") not in {"user", "assistant"}:
            return False
        if message.get("tool_calls"):
            return False
        content = message.get("content", "")
        return isinstance(content, str) and bool(content.strip())
