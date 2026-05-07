"""Rolling conversation summary generation and rendering."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ConversationSummary:
    summary_text: str
    current_goal: str
    progress_summary: str
    important_facts: list[str]
    important_decisions: list[str]
    open_questions: list[str]
    covered_turns: dict
    source_message_count: int

    def to_dict(self) -> dict:
        return {
            "kind": "rolling_conversation_summary",
            "summary_text": self.summary_text,
            "current_goal": self.current_goal,
            "progress_summary": self.progress_summary,
            "important_facts": list(self.important_facts),
            "important_decisions": list(self.important_decisions),
            "open_questions": list(self.open_questions),
            "covered_turns": dict(self.covered_turns),
            "source_message_count": self.source_message_count,
        }


class ConversationSummaryService:
    """Build a compact summary for older user/assistant conversation."""

    def summarize(self, messages: list[dict]) -> dict:
        content_messages = [message for message in messages if self._content_text(message)]
        source_count = len(content_messages)
        user_texts = [self._content_text(message) for message in content_messages if message.get("role") == "user"]
        assistant_texts = [self._content_text(message) for message in content_messages if message.get("role") == "assistant"]

        current_goal = self._shorten(user_texts[-1] if user_texts else "Continue the current conversation.")
        progress_seed = assistant_texts[-1] if assistant_texts else (user_texts[-1] if user_texts else "No prior progress captured.")
        progress_summary = self._shorten(progress_seed)
        important_facts = self._collect_facts(content_messages)
        important_decisions = self._collect_decisions(content_messages)
        open_questions = self._collect_open_questions(content_messages)
        summary_text = self._shorten(
            f"Summarized {source_count} earlier conversation messages while preserving the recent hot zone."
        )
        return ConversationSummary(
            summary_text=summary_text,
            current_goal=current_goal,
            progress_summary=progress_summary,
            important_facts=important_facts,
            important_decisions=important_decisions,
            open_questions=open_questions,
            covered_turns={"start": 1, "end": source_count},
            source_message_count=source_count,
        ).to_dict()

    def render_summary_message(self, summary: dict) -> dict:
        lines = [
            "Conversation summary:",
            f"- current_goal: {summary.get('current_goal') or 'N/A'}",
            f"- progress_summary: {summary.get('progress_summary') or 'N/A'}",
        ]
        self._append_list(lines, "important_facts", summary.get("important_facts") or [])
        self._append_list(lines, "important_decisions", summary.get("important_decisions") or [])
        self._append_list(lines, "open_questions", summary.get("open_questions") or [])
        return {"role": "assistant", "content": "\n".join(lines)}

    def _append_list(self, lines: list[str], title: str, items: list[str]) -> None:
        lines.append(f"- {title}:")
        if not items:
            lines.append("  - None")
            return
        for item in items:
            lines.append(f"  - {item}")

    def _collect_facts(self, messages: list[dict]) -> list[str]:
        facts = []
        for message in messages:
            text = self._content_text(message)
            if not text:
                continue
            facts.append(self._shorten(text))
            if len(facts) >= 3:
                break
        return facts

    def _collect_decisions(self, messages: list[dict]) -> list[str]:
        decisions = []
        keywords = ("decide", "decided", "will ", "use ", "switch", "改为", "决定", "采用")
        for message in messages:
            text = self._content_text(message).lower()
            if not text:
                continue
            if any(keyword in text for keyword in keywords):
                decisions.append(self._shorten(self._content_text(message)))
            if len(decisions) >= 3:
                break
        return decisions

    def _collect_open_questions(self, messages: list[dict]) -> list[str]:
        questions = []
        for message in messages:
            original = self._content_text(message)
            if original and "?" in original:
                questions.append(self._shorten(original))
            if len(questions) >= 3:
                break
        return questions

    def _content_text(self, message: dict) -> str:
        content = message.get("content", "")
        if not isinstance(content, str):
            return ""
        return content.strip()

    def _shorten(self, text: str, limit: int = 160) -> str:
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."
