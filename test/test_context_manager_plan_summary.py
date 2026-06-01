import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.services import ContextManager, SkillSelector
from agent.domain import Skill, SkillMatch


class QueryOnlySession:
    def __init__(self, messages):
        self._messages = [dict(message) for message in messages]

    async def get_messages_slice(self, start=None, end=None, roles=None):
        messages = [dict(message) for message in self._messages]
        if roles:
            allowed = set(roles)
            messages = [message for message in messages if message.get("role") in allowed]
        return messages[slice(start, end)]


class StaticSkillRepository:
    def list_skills(self):
        return [
            Skill(
                name="demo",
                description="Demo skill.",
                body="# Demo",
                path="/tmp/demo/SKILL.md",
                source="project",
            )
        ]


class ChangingPlanProvider:
    def __init__(self):
        self.count = 0

    def build_context(self):
        self.count += 1
        content = f"Active plan summary:\n- Plan: p (version {self.count})"
        return (
            [{"role": "system", "content": content}],
            {
                "plan_summary_chars": len(content),
                "plan_open": True,
                "plan_step_count": 1,
                "plan_unfinished_step_count": 1,
            },
            {
                "plan_summary_injected": True,
                "plan_id": "p",
                "plan_version": self.count,
                "plan_state": "open",
            },
        )


@pytest.mark.asyncio
async def test_context_manager_inserts_plan_summary_before_latest_user_without_inactive_skill_index() -> None:
    provider = ChangingPlanProvider()
    manager = ContextManager(
        plan_context_provider=provider,
        skill_repository=StaticSkillRepository(),
        skill_selector=SkillSelector(),
    )
    session = QueryOnlySession([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "latest question"},
    ])

    result = await manager.build_messages_async(session=session)

    contents = [message.get("content", "") for message in result.messages]
    if contents != [
        "sys",
        "old question",
        "old answer",
        "Active plan summary:\n- Plan: p (version 1)",
        "latest question",
    ]:
        raise AssertionError(f"Expected plan summary before latest user, got: {result.messages}")
    if any(content.startswith("Available skills:") for content in contents):
        raise AssertionError(f"Did not expect inactive skill index, got: {result.messages}")
    if result.stats.get("plan_summary_chars", 0) <= 0:
        raise AssertionError(f"Expected plan stats, got: {result.stats}")
    if result.decisions.get("plan_state") != "open" or not result.decisions.get("plan_summary_injected"):
        raise AssertionError(f"Expected plan decisions, got: {result.decisions}")


@pytest.mark.asyncio
async def test_context_manager_keeps_active_skill_after_system_when_plan_moves_to_tail() -> None:
    provider = ChangingPlanProvider()
    skill = Skill(
        name="demo",
        description="Demo skill.",
        body="# Demo\nUse demo instructions.",
        path="/tmp/demo/SKILL.md",
        source="project",
    )
    manager = ContextManager(
        plan_context_provider=provider,
        skill_repository=StaticSkillRepository(),
        skill_selector=SkillSelector(),
    )
    session = QueryOnlySession([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "latest $demo question"},
    ])

    result = await manager.build_messages_async(
        session=session,
        active_skill_matches=[SkillMatch(skill=skill, reason="explicit_dollar_name", score=100)],
    )

    contents = [message.get("content", "") for message in result.messages]
    if contents[0] != "sys" or not contents[1].startswith("Active skill instructions:"):
        raise AssertionError(f"Expected active skill immediately after system, got: {result.messages}")
    if contents[-2] != "Active plan summary:\n- Plan: p (version 1)" or contents[-1] != "latest $demo question":
        raise AssertionError(f"Expected plan summary before latest user, got: {result.messages}")


@pytest.mark.asyncio
async def test_context_manager_reads_plan_summary_each_build() -> None:
    provider = ChangingPlanProvider()
    manager = ContextManager(plan_context_provider=provider)
    session = QueryOnlySession([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "latest question"},
    ])

    first = await manager.build_messages_async(session=session)
    second = await manager.build_messages_async(session=session)

    first_summary = first.messages[-2]["content"]
    second_summary = second.messages[-2]["content"]
    if "version 1" not in first_summary or "version 2" not in second_summary:
        raise AssertionError(f"Expected fresh plan summary each build, got: {first_summary}, {second_summary}")


@pytest.mark.asyncio
async def test_context_manager_plan_summary_changes_preserve_history_prefix() -> None:
    provider = ChangingPlanProvider()
    manager = ContextManager(plan_context_provider=provider)
    session = QueryOnlySession([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "latest question"},
    ])

    first = await manager.build_messages_async(session=session)
    second = await manager.build_messages_async(session=session)

    first_prefix = first.messages[:3]
    second_prefix = second.messages[:3]
    expected_prefix = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
    ]
    if first_prefix != expected_prefix or second_prefix != expected_prefix:
        raise AssertionError(f"Expected stable history prefix, got: {first.messages} / {second.messages}")
    if first.messages[-2] == second.messages[-2]:
        raise AssertionError(f"Expected plan summary to refresh, got: {first.messages} / {second.messages}")


@pytest.mark.asyncio
async def test_context_manager_appends_plan_summary_when_no_user_message_exists() -> None:
    provider = ChangingPlanProvider()
    manager = ContextManager(plan_context_provider=provider)
    session = QueryOnlySession([
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "assistant only"},
    ])

    result = await manager.build_messages_async(session=session)

    contents = [message.get("content", "") for message in result.messages]
    if contents != [
        "sys",
        "assistant only",
        "Active plan summary:\n- Plan: p (version 1)",
    ]:
        raise AssertionError(f"Expected plan summary appended without user message, got: {result.messages}")


def main() -> int:
    import asyncio

    asyncio.run(test_context_manager_inserts_plan_summary_before_latest_user_without_inactive_skill_index())
    asyncio.run(test_context_manager_keeps_active_skill_after_system_when_plan_moves_to_tail())
    asyncio.run(test_context_manager_reads_plan_summary_each_build())
    asyncio.run(test_context_manager_plan_summary_changes_preserve_history_prefix())
    asyncio.run(test_context_manager_appends_plan_summary_when_no_user_message_exists())
    print("ContextManager plan summary tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
