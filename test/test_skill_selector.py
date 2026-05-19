import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.services import SkillSelector
from agent.domain import Skill


def _skill(name: str, triggers: list[str] | None = None) -> Skill:
    return Skill(
        name=name,
        description=f"{name} description",
        body=f"{name} body",
        path=f"/tmp/{name}/SKILL.md",
        triggers=triggers or [],
    )


def test_skill_selector_prefers_explicit_dollar_name() -> None:
    selector = SkillSelector(max_active_skills=2)
    skills = [_skill("skill-creator", ["create skill"]), _skill("reviewer", ["review code"])]

    matches = selector.select("Please use $skill-creator to create skill docs.", skills)

    if len(matches) != 1:
        raise AssertionError(f"Expected one match, got: {matches}")
    match = matches[0]
    if match.skill.name != "skill-creator" or match.reason != "explicit_dollar_name" or match.score != 100:
        raise AssertionError(f"Unexpected explicit match: {match}")


def test_skill_selector_matches_names_triggers_and_limit() -> None:
    selector = SkillSelector(max_active_skills=2)
    skills = [
        _skill("alpha", ["shared trigger"]),
        _skill("beta", ["shared trigger"]),
        _skill("gamma", ["shared trigger"]),
    ]

    matches = selector.select("Use beta and shared trigger.", skills)

    if [match.skill.name for match in matches] != ["beta", "alpha"]:
        raise AssertionError(f"Expected name match first then trigger sort, got: {matches}")
    if [match.reason for match in matches] != ["explicit_name", "trigger"]:
        raise AssertionError(f"Unexpected match reasons: {matches}")


def test_skill_selector_can_disable_active_skills() -> None:
    selector = SkillSelector(max_active_skills=0)
    matches = selector.select("Use $alpha", [_skill("alpha")])
    if matches:
        raise AssertionError(f"Expected no matches when disabled, got: {matches}")


def main() -> int:
    test_skill_selector_prefers_explicit_dollar_name()
    test_skill_selector_matches_names_triggers_and_limit()
    test_skill_selector_can_disable_active_skills()
    print("Skill selector tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
