# 迭代型 Plan 管理与 Compact Summary 注入实施方案

> 目标：让当前 `plan_*` 工具从“一次性任务清单”升级为适合长期迭代任务的轻量计划系统。它需要支持动态追加步骤、更新长期目标/约束/指标、记录每轮实验观察，并在存在 open plan 时自动向模型注入简短 plan summary，避免长期目标在上下文压缩后丢失。

---

## 1. 背景与问题

当前 plan 机制已经具备：

- `plan_create`：一次性创建计划；
- `plan_get`：读取完整计划；
- `plan_update_step`：更新已有 step；
- `plan_link_dependency`：修改已有依赖；
- `plan_reorder`：调整顺序；
- `plan_next`：找下一个 ready/focus step；
- `plan_close`：关闭计划。

但它不够适合长期迭代型任务，例如：

```text
目标：在一个量化策略框架下，把年化收益优化到 10%，Sharpe 优化到 3。
过程：回测 -> 观察指标 -> 更换方法 -> 再回测 -> 记录结论 -> 追加新实验步骤。
```

当前缺口：

- 不能结构化追加新的 step，只能创建一次性步骤列表；
- 不能结构化更新 plan 的长期目标、约束、最新指标；
- 不能结构化记录每轮回测/实验观察；
- 如果上下文被压缩，模型可能忘记长期目标；
- 旧的 tool result 可能被摘要或截断，不能依赖历史上下文保存 plan 状态；
- 直接用文件编辑工具改 `plan.json` 容易破坏版本号、事件日志、依赖一致性。

核心设计结论：

```text
plan.json = 当前计划状态的唯一真实来源
plan_events.jsonl = 计划变更历史与审计日志
compact plan summary = 每次 context build 时由 plan.json 动态生成的短上下文视图
```

---

## 2. 设计目标

功能目标：

- 支持在 active/open plan 中追加新 step；
- 支持更新 plan 的长期目标、结构化 objectives、constraints、metrics；
- 支持记录每轮实验/回测 observation；
- 有 open plan 时，每次 LLM 请求前自动注入 compact plan summary；
- 没有 plan 或 plan 已关闭时，不注入 plan summary；
- 不把完整 plan steps 每轮塞进上下文；
- 不依赖模型记忆保存长期目标；
- 所有 plan 状态变更都走 plan tool，不建议通过文件编辑工具直接改 `plan.json`。

工程目标：

- 保持代码清晰、短小、低耦合；
- 不引入复杂数据库；
- 保持 session-local 文件存储；
- 保持现有 `expected_version` 乐观锁机制；
- 保持旧 `plan.json` 向后兼容；
- 避免让 `ContextManager` 直接知道 plan tool 的内部细节。

非目标：

- 不实现多 plan 并行；
- 不实现复杂实验管理平台；
- 不实现自动判断量化策略好坏；
- 不实现完整 plan 历史回放 UI；
- 不用 LLM 重新总结 plan，每次 summary 由本地结构化数据确定性渲染。

---

## 3. Active / Open Plan 判断

当前没有常驻变量维护 active plan。判断应以当前 session 目录下的 `plan.json` 为准。

定义：

```text
no_plan:
  plan.json 不存在

closed_plan:
  plan.json 存在，但 status 是 completed 或 canceled

open_plan:
  plan.json 存在，且 status == active

executable_open_plan:
  status == active，且存在 pending / in_progress / blocked step

terminal_open_plan:
  status == active，但所有 step 都是 completed / canceled
```

注入规则：

- `no_plan`：不注入 compact plan summary；
- `closed_plan`：不注入 compact plan summary；
- `executable_open_plan`：注入正常 compact plan summary；
- `terminal_open_plan`：不当作“有可执行步骤”的 active plan，但注入极短维护提示，提醒模型：
  - 如果目标已达成，调用 `plan_close`；
  - 如果目标未达成，调用 `plan_add_step` 开启下一轮迭代。

这样既尊重“所有 step 完成后没有可执行 active plan”的直觉，也避免一个未关闭的 open plan 卡住后续计划管理。

---

## 4. 数据模型扩展

文件仍然是当前 session 下：

```text
<session_root>/<session_id>/plan.json
<session_root>/<session_id>/plan_events.jsonl
```

### 4.1 `plan.json` 新增字段

将 `PLAN_SCHEMA_VERSION` 从 `1.0` 提升到 `1.1`。旧 plan 缺失新字段时按默认值处理，不需要迁移脚本。

新增字段：

```json
{
  "objectives": [],
  "constraints": [],
  "metrics": {},
  "observations": []
}
```

含义：

- `objectives`：长期优化目标，例如年化收益、Sharpe；
- `constraints`：约束条件，例如最大回撤、交易频率、数据范围；
- `metrics`：最新指标快照；
- `observations`：最近若干条实验观察，完整历史仍在 `plan_events.jsonl`。

示例：

```json
{
  "goal": "在当前策略框架下，把年化收益优化到 10%，Sharpe 优化到 3。",
  "objectives": [
    {
      "metric": "annual_return",
      "operator": ">=",
      "target": 0.10,
      "current": 0.072,
      "unit": "ratio"
    },
    {
      "metric": "sharpe",
      "operator": ">=",
      "target": 3.0,
      "current": 1.8,
      "unit": "number"
    }
  ],
  "constraints": [
    {
      "metric": "max_drawdown",
      "operator": "<=",
      "target": 0.12,
      "current": 0.16,
      "unit": "ratio"
    }
  ],
  "metrics": {
    "annual_return": 0.072,
    "sharpe": 1.8,
    "max_drawdown": 0.16
  },
  "observations": [
    {
      "observation_id": "obs_ab12cd34",
      "ts": "2026-05-19T00:00:00+00:00",
      "step_id": "backtest_v3",
      "summary": "加入波动率过滤后 Sharpe 提升，但最大回撤变差。",
      "metrics": {
        "annual_return": 0.072,
        "sharpe": 1.8,
        "max_drawdown": 0.16
      },
      "hypothesis": "需要在高波动阶段降低仓位，而不是直接过滤交易。",
      "next_action": "新增 position_sizing_v4 实验。"
    }
  ]
}
```

### 4.2 Observation 保留策略

- `plan.json["observations"]` 只保留最近 `20` 条；
- `plan_events.jsonl` 保留完整 observation 历史；
- compact summary 默认只展示最新 1 条 observation；
- 如果需要回看更久历史，让模型调用 `plan_get` 或后续专门的 history tool。

---

## 5. 新增 Tool

新增三个 tool，保持工具数量克制，但覆盖长期迭代的关键能力。

### 5.1 `plan_add_step`

用途：向当前 open plan 追加一个新 step，用于新增实验、修复、下一轮假设验证。

建议签名：

```python
def plan_add_step(
    title: str,
    description: str = "",
    step_id: str | None = None,
    depends_on: list[str] | None = None,
    priority: int = 0,
    owner: str = "",
    acceptance: str = "",
    expected_version: int = 0,
) -> str:
    ...
```

行为：

- 读取当前 `plan.json`；
- 要求 `plan.status == "active"`；
- 校验 `expected_version`；
- `title` 非空；
- `step_id` 可选：
  - 未传则自动生成稳定 ID，例如 `step_<n>`，若冲突则递增；
  - 传入则必须唯一；
- `depends_on` 必须引用已有 step；
- 追加到 `steps` 尾部，`order = max(order) + 1`；
- 新 step 初始 `status = "pending"`；
- 校验依赖图无环；
- bump `version`；
- 追加 `plan_events.jsonl` 事件 `step_added`；
- 返回新增 step 和 plan meta。

错误码：

- `NotFound`：没有 plan；
- `ValidationError`：title 空、plan 非 active、字段类型错误；
- `VersionConflict`：版本不一致；
- `DependencyViolation`：依赖不存在；
- `CycleDetected`：依赖成环。

### 5.2 `plan_update_meta`

用途：更新长期目标、约束、最新指标、计划摘要等 plan-level 信息。

建议签名：

```python
def plan_update_meta(
    expected_version: int,
    goal: str | None = None,
    objectives: list[dict] | None = None,
    constraints: list[dict] | None = None,
    metrics: dict | None = None,
    summary: str | None = None,
) -> str:
    ...
```

行为：

- 要求存在 `plan.json`；
- 要求 `plan.status == "active"`；
- 校验 `expected_version`；
- 至少有一个字段被更新；
- `goal` / `summary` 如果传入，strip 后写入；
- `objectives` / `constraints` 如果传入，整体替换；
- `metrics` 如果传入，merge 到现有 `plan["metrics"]`；
- 同步更新 `objectives[*].current` / `constraints[*].current`：
  - 如果 item 有 `metric` 且 `metrics` 里有同名值，则更新 `current`；
- bump `version`；
- 追加事件 `plan_meta_updated`；
- 返回更新后的 plan meta，不必返回完整 steps。

错误码：

- `NotFound`；
- `ValidationError`；
- `VersionConflict`。

### 5.3 `plan_record_observation`

用途：记录一次实验、回测、调查、验证后的结构化观察。

建议签名：

```python
def plan_record_observation(
    summary: str,
    expected_version: int,
    step_id: str | None = None,
    metrics: dict | None = None,
    hypothesis: str = "",
    next_action: str = "",
    tags: list[str] | None = None,
) -> str:
    ...
```

行为：

- 要求存在 `plan.json`；
- 要求 `plan.status == "active"`；
- 校验 `expected_version`；
- `summary` 非空；
- 如果传入 `step_id`，必须引用已有 step；
- 生成 `observation_id`；
- observation 写入 `plan["observations"]` 尾部；
- `plan["observations"]` 超过 20 条时裁剪旧记录；
- 如果传入 `metrics`：
  - merge 到 `plan["metrics"]`；
  - 同步更新 objectives / constraints 的 `current`；
- bump `version`；
- 追加事件 `observation_recorded`，事件 payload 保存完整 observation；
- 返回新增 observation、当前 metrics 和 plan meta。

错误码：

- `NotFound`；
- `ValidationError`；
- `VersionConflict`。

---

## 6. Existing Tool 调整

### 6.1 `plan_create`

保持现有签名兼容，同时新增可选参数：

```python
objectives: list[dict] | None = None
constraints: list[dict] | None = None
metrics: dict | None = None
```

创建时写入默认字段：

```python
"objectives": objectives or [],
"constraints": constraints or [],
"metrics": metrics or {},
"observations": [],
```

如果不想扩大 `plan_create` 参数，也可以让模型创建后立刻调用 `plan_update_meta`。但推荐直接支持可选参数，减少长期目标丢失窗口。

### 6.2 `plan_get`

返回完整 plan，包含新增字段。无需新增参数。

### 6.3 `plan_next`

保留现有 `ready` / `focus` / `blocked_report`。

增强 `focus` 返回 meta：

```json
{
  "reason": "no_ready_steps"
}
```

如果所有 step 都是 completed / canceled：

```json
{
  "reason": "all_steps_terminal"
}
```

这样模型可以明确知道：

- 目标达成：调用 `plan_close`；
- 目标未达成：调用 `plan_add_step` 开启下一轮。

### 6.4 `plan_update_step`

不新增字段。继续用于 step 状态、note、acceptance 等更新。

### 6.5 `plan_close`

保持现有行为：只有所有 step 都 completed / canceled 才允许关闭。

---

## 7. Compact Plan Summary 注入

### 7.1 注入位置

在 `ContextManager.build_messages_async()` 内完成，和 skill index 一样属于 context-only 注入，不持久化为 session message。

推荐顺序：

```text
原始 system prompt
Active plan summary
Available skills / Active skill instructions
历史 messages
```

也就是：plan summary 比 skill 更接近长期任务状态，优先放在 system prompt 后。

### 7.2 注入条件

每次 context build 都读取当前 session 的 `plan.json`：

```text
plan.json 不存在 -> 不注入
status completed/canceled -> 不注入
status active -> 注入 compact summary
```

如果是 `terminal_open_plan`，summary 保持极短：

```text
Open plan has no unfinished steps.
If the goal is satisfied, call plan_close. If not, call plan_add_step for the next iteration.
```

### 7.3 Summary 内容

示例：

```text
Active plan summary:
- Plan: strategy_optimization (version 12)
- Goal: 在当前策略框架下，把年化收益优化到 10%，Sharpe 优化到 3。
- Objectives: annual_return >= 0.10 (current 0.072); sharpe >= 3.0 (current 1.8)
- Constraints: max_drawdown <= 0.12 (current 0.16)
- Progress: completed=5, in_progress=1, blocked=0, pending=3, canceled=0
- Current focus: backtest_v4 - 测试动态仓位控制
- Acceptance: Sharpe 提升且 max_drawdown <= 0.12
- Latest metrics: annual_return=0.072, sharpe=1.8, max_drawdown=0.16
- Latest observation: 加入波动率过滤后 Sharpe 提升，但最大回撤变差。
- Next action: 新增 position_sizing_v4 实验。
```

渲染规则：

- 不展示完整 steps；
- 最多展示 3 个 objectives；
- 最多展示 3 个 constraints；
- 最多展示 8 个 metrics；
- 只展示 1 个 current focus：
  - 优先 `in_progress`；
  - 否则 `pending` 且依赖已完成；
  - 否则第一个 `blocked`；
  - 否则无 focus；
- 只展示最新 1 条 observation；
- 默认字符上限 `2200`；
- 超出时截断并加提示。

### 7.4 Context stats / decisions

`ContextManager` 的 `stats` 增加：

```python
"plan_summary_chars": int,
"plan_open": bool,
"plan_step_count": int,
"plan_unfinished_step_count": int,
```

`decisions` 增加：

```python
"plan_summary_injected": bool,
"plan_id": str | None,
"plan_version": int | None,
"plan_state": "none" | "closed" | "open" | "terminal_open" | "error",
```

---

## 8. 代码结构建议

为了避免 `plan.py` 继续膨胀，建议做一个很小的模块拆分。

新增目录：

```text
agent/infrastructure/plans/
  __init__.py
  store.py
  summary.py
  context_provider.py
```

### 8.1 `store.py`

职责：session plan 文件 IO 和事件写入。

建议包含：

```python
def now_iso() -> str: ...
def resolve_session_base() -> tuple[Path, str]: ...
def plan_paths() -> tuple[Path, Path, str]: ...
def load_plan() -> tuple[dict, Path, Path]: ...
def load_plan_if_exists() -> dict | None: ...
def write_json_atomic(path: Path, data: dict) -> None: ...
def append_event(events_file: Path, event: dict) -> None: ...
def persist_plan_update(plan: dict, plan_file: Path, events_file: Path, event_type: str, payload: dict) -> None: ...
```

`agent/infrastructure/tools/impl/tools/plan.py` 改为复用这些 helper，避免 context provider 和 tool 各自复制路径逻辑。

### 8.2 `summary.py`

职责：纯函数渲染 compact summary，不读写文件。

建议包含：

```python
TERMINAL_STEP_STATUS = {"completed", "canceled"}

def step_counts(plan: dict) -> dict[str, int]: ...
def unfinished_steps(plan: dict) -> list[dict]: ...
def is_terminal_open_plan(plan: dict) -> bool: ...
def render_compact_plan_summary(plan: dict, char_limit: int = 2200) -> str: ...
```

### 8.3 `context_provider.py`

职责：把 session plan 转成 ContextManager 可注入的 system message。

建议接口：

```python
class PlanContextProvider:
    def __init__(self, char_limit: int = 2200):
        self._char_limit = max(0, int(char_limit))

    def build_context(self) -> tuple[list[dict], dict, dict]:
        ...
```

返回：

```python
messages = [{"role": "system", "content": summary}] 或 []
stats = {...}
decisions = {...}
```

内部捕获：

- plan 文件不存在：返回 no plan；
- plan 文件损坏：不抛到主流程，返回 `plan_state="error"`；
- status closed：不注入。

### 8.4 `ContextManager`

构造函数新增可选参数：

```python
plan_context_provider=None
```

在 `build_messages_async()` 中：

```python
plan_messages, plan_stats, plan_decisions = self._build_plan_messages()
skill_messages, skill_stats, skill_decisions = self._build_skill_messages(active_skill_matches)
extra_messages = plan_messages + skill_messages
full_messages = self._insert_after_first_system(full_messages, extra_messages)
```

注意：

- plan summary 不持久化为 message；
- 每次 context build 都重新读取 `plan.json`；
- tool call 后再次请求 LLM 时，会拿到最新 plan summary；
- 没有 plan 时没有额外上下文负担。

### 8.5 `container.py`

在 bootstrap 中创建：

```python
plan_context_provider = PlanContextProvider(char_limit=2200)
context_manager = ContextManager(..., plan_context_provider=plan_context_provider)
```

---

## 9. Tool 注册

更新：

```text
agent/infrastructure/tools/impl/tools/__init__.py
agent/infrastructure/tools/impl/__init__.py
```

新增导出：

```python
plan_add_step
plan_update_meta
plan_record_observation
```

新增 `TOOLS` 注册。

新增 schema meta，重点写清：

- 必须使用 `expected_version`；
- 不要直接编辑 `plan.json`；
- `plan_add_step` 用于动态追加步骤；
- `plan_record_observation` 用于记录实验/回测结果；
- `plan_update_meta` 用于更新目标、约束、指标。

---

## 10. Prompt 调整

文件：

```text
agent/prompts.py
```

更新 planning protocol：

- 对长期、多轮、实验迭代任务，必须使用 plan；
- 当当前 plan 不覆盖下一步时，调用 `plan_add_step`；
- 每轮实验、回测、验证后，调用 `plan_record_observation`；
- 当长期目标、约束或最新指标变化时，调用 `plan_update_meta`；
- 如果 `plan_next("focus")` 返回 `all_steps_terminal`：
  - 目标达成：调用 `plan_close`；
  - 目标未达成：调用 `plan_add_step`；
- 不要通过文件编辑工具直接修改 `plan.json`。

---

## 11. 测试计划

### 11.1 Plan tool 测试

新增或扩展：

```text
test/test_plan_tool.py
```

覆盖：

- `plan_create` 写入默认 `objectives/constraints/metrics/observations`；
- `plan_create` 接收可选 metadata；
- `plan_add_step` 成功追加 step；
- `plan_add_step` 自动生成不冲突 step_id；
- `plan_add_step` 拒绝重复 step_id；
- `plan_add_step` 拒绝未知 depends_on；
- `plan_add_step` 遵守 expected_version；
- `plan_update_meta` 更新 goal；
- `plan_update_meta` 替换 objectives/constraints；
- `plan_update_meta` merge metrics；
- `plan_update_meta` 同步 objectives/constraints current；
- `plan_record_observation` 追加 observation；
- `plan_record_observation` merge metrics；
- `plan_record_observation` 写入 `plan_events.jsonl`；
- observations 超过 20 条时 `plan.json` 只保留最近 20 条；
- `plan_next("focus")` 在所有 step terminal 时返回 `reason=all_steps_terminal`；
- `plan_close` 后新增 mutation tool 拒绝修改。

### 11.2 Compact summary 测试

新增：

```text
test/test_plan_context_summary.py
```

覆盖：

- 没有 `plan.json` 时不注入；
- `status=completed` 时不注入；
- `status=active` 且有 unfinished steps 时注入 summary；
- summary 包含 goal、version、progress、current focus；
- summary 包含 objectives / constraints / metrics；
- summary 包含 latest observation；
- summary 不包含完整 step 列表；
- terminal open plan 注入极短维护提示；
- summary 超过 char limit 会截断；
- plan 文件损坏时不破坏 context build，decision 标记 `plan_state="error"`。

### 11.3 ContextManager 集成测试

扩展：

```text
test/test_context_manager.py
```

或新增专门测试：

```text
test/test_context_manager_plan_summary.py
```

覆盖：

- plan summary 被插入原始 system prompt 后；
- skill index 仍正常注入；
- plan summary 在 skill index 前；
- `stats` / `decisions` 包含 plan 字段；
- 每次 build 都读取最新 plan 状态。

### 11.4 Tool schema 测试

覆盖：

- `TOOLS` 包含三个新 tool；
- schema meta 包含关键参数说明；
- `expected_version` 是 mutation tool 的必填参数。

---

## 12. 回归命令

执行：

```bash
python -m compileall -q .
python test/test_plan_tool.py
python test/test_plan_context_summary.py
pytest test/test_plan_tool.py test/test_plan_context_summary.py test/test_context_manager.py -q
```

如果已有全量测试存在无关失败，至少保证上述 plan 相关测试全部通过。

---

## 13. 验收标准

功能验收：

- 可以在已有 active plan 中追加新 step；
- 可以结构化更新长期目标、约束、最新指标；
- 可以记录每轮实验/回测 observation；
- observation 完整历史写入 `plan_events.jsonl`；
- `plan.json` 只保存 compact recent observations；
- 有 open plan 时，每次 LLM 请求都会自动收到 compact plan summary；
- 没有 plan 或 plan closed 时，不注入 summary；
- summary 不包含完整 steps，不造成长期上下文膨胀；
- 上下文压缩后，长期目标仍可从 plan summary 恢复；
- 所有 mutation tool 都遵守 `expected_version`。

工程验收：

- 不通过 edit file 直接修改 plan 状态；
- `ContextManager` 不直接依赖 plan tool 函数；
- plan 文件 IO 集中在 `agent/infrastructure/plans/store.py`；
- summary 渲染是确定性纯逻辑；
- 新增代码保持小函数、清晰职责；
- 不引入大型抽象或数据库；
- 单文件不超过仓库约定硬限制。

---

## 14. 推荐实现顺序

1. 新增 `agent/infrastructure/plans/store.py`，迁移 plan 文件 IO helper；
2. 新增 `agent/infrastructure/plans/summary.py`，实现 compact summary 纯函数；
3. 新增 `agent/infrastructure/plans/context_provider.py`；
4. 在 `ContextManager` 中接入 plan summary 注入；
5. 在 `plan.py` 中新增 `plan_add_step`、`plan_update_meta`、`plan_record_observation`；
6. 给 `plan_create` 增加可选 metadata；
7. 更新 tool exports / `TOOLS` / schema meta；
8. 更新 `agent/prompts.py` planning protocol；
9. 添加并运行测试；
10. 最后检查 `plan.py` 是否过长，如明显臃肿，再把纯 mutation helper 拆到 `agent/infrastructure/plans/operations.py`。

