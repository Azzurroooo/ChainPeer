"""Context construction service for model-facing conversation state."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    """Builds the model-facing message list from persisted session state.

    Step 1C shifts context assembly away from an in-memory full-history list.
    The session store is now the primary source of truth, while
    ``pending_messages`` can provide a small in-memory overlay for messages that
    have not been persisted yet.
    """

    def build_messages(self, session, pending_messages: list[dict] | None = None) -> ContextBuildResult:
        persisted_messages = [dict(message) for message in session.get_messages_slice()]
        pending = [dict(message) for message in (pending_messages or [])]
        messages = persisted_messages + pending

        system_message = next((dict(message) for message in messages if message.get("role") == "system"), None)
        non_system_messages = [dict(message) for message in messages if message.get("role") != "system"]
        tool_messages = [dict(message) for message in messages if message.get("role") == "tool"]

        snapshot = ContextSnapshot(
            system_message=system_message,
            recent_messages=non_system_messages,
            tool_messages=tool_messages,
        )
        stats = {
            "message_count": len(messages),
            "persisted_message_count": len(persisted_messages),
            "pending_message_count": len(pending),
            "tool_message_count": len(tool_messages),
        }
        decisions = {
            "mode": "session_backed",
            "source": "session_queries",
            "uses_pending_overlay": bool(pending),
        }
        return ContextBuildResult(messages=messages, stats=stats, decisions=decisions, snapshot=snapshot)
