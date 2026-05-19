# ChainPeer Skill Format

Skills live in one of these locations:

- Project scope: `.chainpeer/skills/<skill_name>/SKILL.md`
- User scope: `~/.chainpeer/skills/<skill_name>/SKILL.md`

Project skills override user skills with the same name.

## Minimal Example

```markdown
---
name: skill-creator
description: Create or update ChainPeer skills with a valid SKILL.md structure.
triggers:
  - create skill
  - update skill
---

# Skill Instructions

Use this skill when the user asks to create or update a ChainPeer skill.

## Workflow

1. Inspect the target skill directory.
2. Create or update `SKILL.md`.
3. Keep instructions concise and operational.
```

## Fields

- `name`: Required. Should match the skill directory name.
- `description`: Required. Used in the compact skill index.
- `triggers`: Optional. Short phrases that activate the skill when the user does not explicitly name it.

## First-Version Limits

- Only `SKILL.md` is read automatically.
- Adjacent folders such as `references/`, `scripts/`, and `assets/` are not expanded automatically.
- Use `$skill-name` in a user request to force a specific skill.
- Keep the body focused; active skill instructions are injected with a character budget.

