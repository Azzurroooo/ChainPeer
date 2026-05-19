"""Deterministic selection of active skills for a user message."""

from __future__ import annotations

import re

from agent.domain.skills import Skill, SkillMatch


class SkillSelector:
    """Select skills using explicit names and declared trigger phrases."""

    def __init__(self, max_active_skills: int = 2):
        self._max_active_skills = max(0, int(max_active_skills))

    def select(self, user_message: str, skills: list[Skill]) -> list[SkillMatch]:
        if self._max_active_skills <= 0 or not user_message or not skills:
            return []

        text = user_message.lower()
        explicit_names = set(re.findall(r"\$([a-zA-Z0-9_-]+)", user_message))
        explicit_names = {item.lower() for item in explicit_names}
        matches: dict[str, SkillMatch] = {}

        for skill in skills:
            key = skill.name.lower()
            candidate: SkillMatch | None = None

            if key in explicit_names:
                candidate = SkillMatch(skill=skill, reason="explicit_dollar_name", score=100)
            elif key and key in text:
                candidate = SkillMatch(skill=skill, reason="explicit_name", score=80)
            else:
                for trigger in skill.triggers:
                    normalized = trigger.lower().strip()
                    if normalized and normalized in text:
                        candidate = SkillMatch(skill=skill, reason="trigger", score=60)
                        break

            if candidate:
                existing = matches.get(key)
                if existing is None or candidate.score > existing.score:
                    matches[key] = candidate

        ordered = sorted(matches.values(), key=lambda item: (-item.score, item.skill.name.lower()))
        return ordered[: self._max_active_skills]

