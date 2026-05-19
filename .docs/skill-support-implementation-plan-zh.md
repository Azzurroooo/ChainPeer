# Skill 功能支持最小落地方案

> 目标受众：Codex / Claude Code / 其他 AI 编程助手  
> 任务目标：在现有 ChainPeer Agent 中加入可用、可控、低上下文膨胀的 Skill 支持。  
> 核心原则：第一版把 Skill 作为“上下文能力”接入，而不是优先做成新的工具能力。

---

## 1. 背景与目标

当前 Agent 已具备：

- 工具注册与 OpenAI function schema 自动生成；
- 异步 runtime 与 streaming 输出；
- JSONL 会话持久化与恢复；
- `ContextManager` 的上下文预算、工具输出热度压缩、rolling summary；
- 现有工具数量已经不少，继续新增工具会增加 system/tool schema 成本。

本次目标是在不破坏现有架构的前提下，加入 Skill 支持：

1. Agent 能发现本地定义的 skill；
2. Agent 默认只看到精简 skill index；
3. 当用户显式点名或语义触发 skill 时，才把对应 `SKILL.md` 正文注入模型上下文；
4. Skill 注入必须受预算与数量限制；
5. 第一版不新增 `create_skill` tool，避免工具 schema 继续膨胀；
6. 保留后续新增 `skill_validate` / `skill_create` tool 的扩展位置。

---

## 2. 非目标

第一版不做以下事项：

- 不做 embedding 检索；
- 不做 LLM 分类器来选择 skill；
- 不新增 `create_skill` / `install_skill` / `validate_skill` 工具；
- 不自动展开 `references/`、`scripts/`、`assets/` 等附属目录内容；
- 不执行 skill 中声明的脚本；
- 不实现远程 skill marketplace；
- 不改造现有 tool schema 生成机制。

如果需要创建 skill，第一版由 Agent 使用已有 `write_file` / `edit_file` 工具直接创建 `SKILL.md`，并由文档模板约束格式。

---

## 3. Skill 文件规范

### 3.1 目录约定

支持两类 skill 目录，优先级从高到低：

1. 项目级：
   - `.chainpeer/skills/<skill_name>/SKILL.md`
2. 用户级：
   - `~/.chainpeer/skills/<skill_name>/SKILL.md`

当项目级与用户级 skill 同名时，项目级覆盖用户级。

### 3.2 `SKILL.md` 推荐格式

使用 Markdown frontmatter：

```markdown
---
name: skill-creator
description: Create or update ChainPeer skills with a valid SKILL.md structure.
triggers:
  - create skill
  - update skill
  - skill file
---

# Skill Instructions

Use this skill when the user asks to create or update a ChainPeer skill.

## Workflow

1. Inspect the target skill directory.
2. Create or update `SKILL.md`.
3. Keep instructions concise and operational.
```

### 3.3 必填与可选字段

必填：

- `name: str`
- `description: str`

可选：

- `triggers: list[str]`

解析规则：

- `name` 必须匹配目录名，若不匹配，repository 应保留该 skill 但记录 warning；
- `description` 用于 skill index；
- `triggers` 用于简单关键词匹配；
- frontmatter 缺失时，允许 fallback：
  - `name` 使用目录名；
  - `description` 使用正文中第一段非标题文本，最长 200 字符；
  - `triggers` 为空。

---

## 4. 架构设计

### 4.1 新增模块

建议新增：

```text
agent/
├── domain/
│   └── skills.py
├── application/
│   └── services/
│       └── skill_selector.py
└── infrastructure/
    └── skills/
        ├── __init__.py
        └── skill_repository.py
```

### 4.2 责任划分

`agent/domain/skills.py`

- 定义 skill 数据结构；
- 提供轻量解析 helper；
- 不访问文件系统；
- 不依赖 application / infrastructure。

`agent/infrastructure/skills/skill_repository.py`

- 扫描 skill 目录；
- 读取 `SKILL.md`；
- 调用 domain parser；
- 处理 project/user 覆盖规则；
- 对外提供 skill index 与按 name 获取 skill。

`agent/application/services/skill_selector.py`

- 根据最近用户消息选择 active skills；
- 只做确定性规则，不调用模型；
- 限制注入数量；
- 输出 selector 决策，便于测试。

`agent/application/services/context_manager.py`

- 构建模型消息时注入 skill index；
- 命中时注入 active skill 正文；
- 所有注入内容以额外 system message 形式出现；
- 受字符预算与最大 skill 数限制。

`agent/bootstrap/container.py`

- 装配 repository 与 selector；
- 将它们注入 `ContextManager`。

---

## 5. 具体实现计划

### Step 1：新增 domain 对象

文件：`agent/domain/skills.py`

建议实现：

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    body: str
    path: str
    triggers: list[str] = field(default_factory=list)
    source: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SkillMatch:
    skill: Skill
    reason: str
    score: int = 0
```

还需要提供：

- `parse_skill_markdown(text: str, path: str, fallback_name: str, source: str) -> Skill`
- `render_skill_index(skills: list[Skill], max_description_chars: int = 180) -> str`
- `render_active_skill_instructions(matches: list[SkillMatch], max_body_chars: int = 6000) -> str`

解析 frontmatter 不建议引入新依赖，第一版可手写一个窄解析器：

- 仅当文件以 `---` 开头时解析；
- 第二个 `---` 之前为 metadata；
- 支持：
  - `name: value`
  - `description: value`
  - `triggers:` 后续 `- item`
- 其余字段忽略；
- 若解析失败，fallback 到目录名和正文摘要。

验收：

- 无 frontmatter 也可解析；
- frontmatter 格式不完整时不抛异常；
- 返回对象带 warnings。

### Step 2：新增 SkillRepository

文件：

- `agent/infrastructure/skills/__init__.py`
- `agent/infrastructure/skills/skill_repository.py`

建议接口：

```python
class SkillRepository:
    def __init__(
        self,
        project_root: str | None = None,
        user_home: str | None = None,
        project_skill_dir: str | None = None,
        user_skill_dir: str | None = None,
    ):
        ...

    def list_skills(self) -> list[Skill]:
        ...

    def get_skill(self, name: str) -> Skill | None:
        ...
```

目录解析：

- `project_root` 默认 `os.getcwd()`；
- `project_skill_dir` 默认 `<project_root>/.chainpeer/skills`；
- `user_skill_dir` 默认 `~/.chainpeer/skills`；
- 仅扫描一级目录下的 `SKILL.md`；
- 先读 user skills，再读 project skills，以便项目级覆盖同名项；
- skill 名称统一小写匹配，但保留原始 `Skill.name`；
- 文件读取使用 UTF-8，`errors="replace"`。

错误处理：

- 单个 skill 文件损坏不能导致整体失败；
- 读取失败时跳过该 skill；
- repository 不应打印日志，必要信息放入 `Skill.warnings`。

验收：

- 空目录返回 `[]`；
- 同名 project skill 覆盖 user skill；
- `get_skill("Name")` 大小写不敏感。

### Step 3：新增 SkillSelector

文件：`agent/application/services/skill_selector.py`

建议接口：

```python
class SkillSelector:
    def __init__(self, max_active_skills: int = 2):
        self._max_active_skills = max(0, int(max_active_skills))

    def select(self, user_message: str, skills: list[Skill]) -> list[SkillMatch]:
        ...
```

选择规则，按优先级：

1. 显式 `$skill_name` 命中，reason=`explicit_dollar_name`，score=100；
2. 文本中出现完整 skill name 命中，reason=`explicit_name`，score=80；
3. 文本中出现 trigger 命中，reason=`trigger`，score=60；
4. 文本中出现 description 中的重要短语可选命中，第一版可以不做，避免误触发。

实现细节：

- 匹配统一使用 lower-case；
- `$skill_name` 支持 `-`、`_`、字母、数字；
- 去重：同一个 skill 只保留最高分 match；
- 排序：score 降序，name 升序；
- 截断到 `max_active_skills`；
- `max_active_skills=0` 时永不注入正文，但仍可注入 index。

验收：

- `$skill-creator` 精确命中；
- trigger 命中；
- 多个命中时按 score 排序；
- 数量不超过上限。

### Step 4：扩展 ContextManager

文件：`agent/application/services/context_manager.py`

构造函数新增可选依赖：

```python
def __init__(
    ...,
    skill_repository=None,
    skill_selector=None,
    skill_index_char_limit: int = 3000,
    active_skill_char_limit: int = 12000,
):
```

不要强制类型绑定 infrastructure，避免 application 反向依赖。可使用 duck typing：

- repository 需要有 `list_skills()`；
- selector 需要有 `select(user_message, skills)`。

在 `build_messages_async()` 中：

1. 读取 persisted messages 后，找最近一条 user message；
2. 调用 repository 获取 skills；
3. 总是生成短 skill index system message，前提是 skills 非空；
4. 用 selector 选择 active skills；
5. 若有 active skills，生成 active skill instructions system message；
6. 将这些 system message 插入 system prompt 后、普通 conversation 前。

建议新增私有方法：

```python
def _latest_user_content(self, messages: list[dict]) -> str:
    ...

def _build_skill_messages(self, user_message: str) -> tuple[list[dict], dict]:
    ...
```

skill index message 格式：

```text
Available skills:
- skill-name: short description
- another-skill: short description

Activation rules:
- Use a skill when the user explicitly names it with $skill-name or when the request clearly matches its description/triggers.
- Only follow active skill instructions when they are provided below.
```

active skill message 格式：

```text
Active skill instructions:

<skill name="skill-name" reason="explicit_dollar_name" source="project">
...SKILL.md body...
</skill>
```

预算控制：

- skill index 总字符数最多 `skill_index_char_limit`；
- active skill 正文总字符数最多 `active_skill_char_limit`；
- 超出时尾部追加：
  - `...(skill instructions truncated due to context budget)...`

统计字段建议加入 `stats`：

- `skill_count`
- `active_skill_count`
- `skill_index_chars`
- `active_skill_chars`

决策字段建议加入 `decisions`：

- `skills_available`
- `active_skills`
- `skill_injection_applied`

重要：这些字段必须兼容旧测试，新增字段不应改变现有字段语义。

验收：

- 没有 skill 时上下文完全不多出 skill message；
- 有 skill 但未命中时只注入 index；
- 命中 skill 时注入 index + active body；
- 注入 message 角色为 `system`；
- 原有 summary / tool temperature 逻辑仍通过测试。

### Step 5：装配 container

文件：`agent/bootstrap/container.py`

新增 imports：

```python
from agent.application.services.skill_selector import SkillSelector
from agent.infrastructure.skills import SkillRepository
```

构造：

```python
skill_repository = SkillRepository()
skill_selector = SkillSelector(max_active_skills=2)

context_manager = ContextManager(
    skill_repository=skill_repository,
    skill_selector=skill_selector,
)
```

然后把 `context_manager` 传给 `AsyncTurnRunner`，替换当前内联 `ContextManager()`。

建议将 dependency dict 中额外返回：

```python
"skill_repository": skill_repository,
"skill_selector": skill_selector,
```

验收：

- `python -m compileall -q .` 通过；
- `build_basic_agent_dependencies()` 不需要 skill 目录也能成功；
- API 与 CLI 都走同一个 skill 注入逻辑。

### Step 6：导出 application service

文件：`agent/application/services/__init__.py`

如果该文件当前导出了其他 service，应加入：

```python
from .skill_selector import SkillSelector
```

验收：

- 测试可从 `agent.application.services import SkillSelector` 导入。

### Step 7：新增文档模板

建议新增：

- `.docs/skill-format.md`

内容包括：

- skill 目录结构；
- `SKILL.md` frontmatter 示例；
- 字段说明；
- 编写建议；
- 第一版限制。

此文档不是运行必需，但可以减少后续 agent 创建 skill 时的格式漂移。

---

## 6. 测试计划

### 6.1 新增 `test/test_skill_repository.py`

覆盖：

1. 空 skill 目录返回空列表；
2. 能解析 frontmatter；
3. 无 frontmatter 时 fallback；
4. user/project 同名时 project 覆盖 user；
5. 损坏 frontmatter 不抛异常。

建议使用 `tmp_path`，不要写真实用户目录。

### 6.2 新增 `test/test_skill_selector.py`

覆盖：

1. `$skill_name` 命中；
2. skill name 文本命中；
3. trigger 命中；
4. 多个 skill 命中时按 score 排序；
5. `max_active_skills` 生效。

### 6.3 新增 `test/test_context_manager_skills.py`

可复用 `test/test_context_manager.py` 中的 fake session 模式。

覆盖：

1. 无 skill 时不注入 skill message；
2. 有 skill 未命中时只注入 index；
3. 显式 `$skill-name` 时注入 active body；
4. stats/decisions 包含 skill 字段；
5. skill 注入不破坏原始 system/user/assistant 顺序。

### 6.4 回归命令

至少运行：

```bash
python -m compileall -q .
python test/test_skill_repository.py
python test/test_skill_selector.py
python test/test_context_manager_skills.py
python test/test_context_manager.py
```

如果仓库已有 pytest 可用，再运行：

```bash
pytest test/ -q
```

---

## 7. 兼容性与风险控制

### 7.1 上下文膨胀风险

控制措施：

- 默认只注入 skill index；
- active skill 最多 2 个；
- index 与 body 都有字符上限；
- 不自动展开附属文件。

### 7.2 误触发风险

控制措施：

- 第一版不做 description 模糊匹配；
- 优先显式 `$skill_name`；
- trigger 由 skill 作者声明；
- active skills 数量受限。

### 7.3 架构耦合风险

控制措施：

- domain 不依赖任何上层；
- application 通过 duck typing 使用 repository；
- infrastructure 只负责文件系统；
- container 是唯一装配点。

### 7.4 会话恢复风险

Skill 不需要持久化到 session。恢复会话时按当前文件系统重新扫描 skill。

这是有意设计：

- skill 更新后立即生效；
- session 文件不膨胀；
- 不需要 migration。

如未来需要审计某轮使用了哪些 skill，可以只把 `ContextManager` 的 snapshot 中的 `decisions.active_skills` 持久化。

---

## 8. 是否新增 create_skill tool 的决策

第一版不新增。

理由：

- 现有工具已经能创建文件；
- 新增 tool 会增加所有请求的 tool schema 成本；
- skill 创建不是每轮高频行为；
- 真正高价值的是 skill selection + context injection。

建议二阶段优先考虑 `skill_validate`，而不是 `skill_create`。

二阶段条件：

- Agent 频繁写错 `SKILL.md` frontmatter；
- 用户经常创建 skill；
- 需要在写入前给出结构化校验报告。

二阶段可选工具：

```python
def skill_validate(skill_dir: str) -> str:
    """Validate a SKILL.md file and return structured errors/warnings."""
```

`skill_create` 只有在 validate 仍不足时再加：

```python
def skill_create(name: str, description: str, triggers: list[str], body: str, scope: str = "project") -> str:
    """Create a valid project/user skill directory with SKILL.md."""
```

---

## 9. 给 Codex 的精确执行指令

实现时按以下顺序执行，不要跳步：

1. 读取 `agent/application/services/context_manager.py`、`agent/bootstrap/container.py`、`agent/application/services/__init__.py`；
2. 新增 `agent/domain/skills.py`，实现 dataclass 与 markdown parser；
3. 新增 `agent/infrastructure/skills/` 包与 `SkillRepository`；
4. 新增 `agent/application/services/skill_selector.py`；
5. 修改 `ContextManager` 构造函数与 `build_messages_async()`，加入 skill index/body 注入；
6. 修改 `container.py`，装配 repository/selector/context_manager；
7. 修改 services `__init__.py` 导出；
8. 新增测试：
   - `test/test_skill_repository.py`
   - `test/test_skill_selector.py`
   - `test/test_context_manager_skills.py`
9. 运行最小测试命令；
10. 若现有测试因新增字段顺序变化失败，优先修正注入位置，不要删除原有断言。

实施约束：

- 不新增第三方依赖；
- 不新增 tool schema；
- 不修改 `SYSTEM_PROMPT` 常量正文，skill 注入通过额外 system message 完成；
- 不读取 skill 附属目录内容；
- 单文件尽量保持 400 行以内；
- 所有新增代码使用 UTF-8、4 空格缩进；
- 错误处理应降级为空 skill，而不是阻断 Agent 启动。

---

## 10. 完成验收标准

功能验收：

- 项目存在 `.chainpeer/skills/demo/SKILL.md` 时，模型上下文包含 `Available skills`；
- 用户输入包含 `$demo` 时，模型上下文包含 demo 的 active instructions；
- 用户未命中 demo 时，不注入 demo 正文；
- 没有任何 skill 目录时，Agent 正常启动且上下文不变。

工程验收：

- `python -m compileall -q .` 通过；
- 新增 skill 相关测试通过；
- 原 `test/test_context_manager.py` 通过；
- CLI 与 API 都通过 `container.py` 装配获得同一套 skill 行为；
- 未新增任何 OpenAI function tool schema。

