import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.infrastructure.skills import SkillRepository


def test_skill_repository_scans_and_overrides(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    user_home = tmp_path / "home"
    project_skill_dir = project_root / ".chainpeer" / "skills"
    user_skill_dir = user_home / ".chainpeer" / "skills"

    (user_skill_dir / "demo").mkdir(parents=True)
    (user_skill_dir / "demo" / "SKILL.md").write_text(
        """---
name: demo
description: user demo skill
triggers:
  - user trigger
---

# Demo
User body.
""",
        encoding="utf-8",
    )

    (project_skill_dir / "demo").mkdir(parents=True)
    (project_skill_dir / "demo" / "SKILL.md").write_text(
        """---
name: demo
description: project demo skill
triggers:
  - project trigger
---

# Demo
Project body.
""",
        encoding="utf-8",
    )

    (project_skill_dir / "fallback").mkdir(parents=True)
    (project_skill_dir / "fallback" / "SKILL.md").write_text(
        """
# Fallback
This skill has no frontmatter.
""".lstrip(),
        encoding="utf-8",
    )

    repo = SkillRepository(
        project_root=str(project_root),
        user_home=str(user_home),
        project_skill_dir=str(project_skill_dir),
        user_skill_dir=str(user_skill_dir),
    )

    skills = repo.list_skills()
    if [skill.name for skill in skills] != ["demo", "fallback"]:
        raise AssertionError(f"Unexpected skill names: {[skill.name for skill in skills]}")

    demo = repo.get_skill("DEMO")
    if not demo or demo.description != "project demo skill" or demo.source != "project":
        raise AssertionError(f"Expected project override, got: {demo}")
    if "project trigger" not in demo.triggers:
        raise AssertionError(f"Expected project triggers, got: {demo.triggers}")

    fallback = repo.get_skill("fallback")
    if not fallback or not fallback.description:
        raise AssertionError(f"Expected fallback description, got: {fallback}")
    if fallback.source != "project":
        raise AssertionError(f"Expected project source, got: {fallback.source}")
    if fallback.warnings:
        raise AssertionError(f"Unexpected warnings for fallback skill: {fallback.warnings}")


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        test_skill_repository_scans_and_overrides(Path(temp_dir))
    print("Skill repository tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
