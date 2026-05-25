# Plan 只保留任务控制状态的重构方案

## 1. 目标

将 plan 从“任务计划 + 模型事实记忆”收敛为“纯任务控制状态”。

核心原则：

- plan 只记录任务结构和执行状态。
- 不再让模型把 observation、metrics、hypothesis、next_action 这类自由总结写入长期状态。
- compact plan summary 只提示当前任务进度和下一步焦点。
- 事实需要时由模型重新读取文件、命令输出、日志、网页或项目内容获取。
- 不引入场景专用 artifact schema，保持通用 agent 设计。

## 2. 当前问题

当前 plan 支持 `plan_record_observation`，并会将最近 observation 与 metrics 注入上下文。问题是：

- observation 的内容由模型填写，系统只校验格式，不校验事实。
- 如果模型填错，错误会进入 `plan.json` 并影响后续 context。
- 如果模型漏写，plan 会停留在旧状态，导致上下文过期。
- metrics 也可能由模型手填，容易被误当作事实。
- 对通用 agent 来说，不存在稳定通用的自动 metrics/artifact 抽取方式。

因此，最小且更稳的改法是：移除 plan 的事实记忆能力，只保留调度状态。

## 3. 保留的 Plan 内容

继续保留：

- `title`
- `goal`
- `steps`
- `depends_on`
- `status`
- `priority`
- `acceptance`
- `blocked_reason`
- `note`，但仅作为短状态备注，不写事实结论
- `objectives`
- `constraints`
- `version`
- `plan_events.jsonl` 中的结构化状态变更事件

建议 `note` 只用于极短执行提示，例如：

- `waiting for test command to finish`
- `blocked by missing dependency`
- `needs user decision`

不用于保存实验结论、指标总结或长文本分析。

## 4. 移除或停用的内容

### 4.1 移除公开 tool

移除模型可调用的：

- `plan_record_observation`

涉及文件：

- `agent/infrastructure/tools/impl/tools/plan.py`
- `agent/infrastructure/tools/impl/tools/__init__.py`
- `agent/infrastructure/tools/impl/__init__.py`
- `agent/prompts.py`

要求：

- 从 `TOOLS` 注册中移除。
- 从 tool schema/meta 中移除。
- 从导出列表中移除。
- 从系统提示词中移除所有 `plan_record_observation` 相关描述。

### 4.2 停止注入 observation/metrics

修改 `agent/infrastructure/plans/summary.py`：

- 删除 compact summary 中的 `Latest metrics`。
- 删除 `Latest observation`。
- 删除 `Hypothesis`。
- 删除 `Next action`。
- 删除 `_latest_observation()` 及仅为 observation 服务的辅助逻辑。
- 删除 `_format_metrics()`，如果不再被其他逻辑使用。

compact plan summary 保留：

- Plan title/version
- Goal
- Objectives
- Constraints
- Progress
- Current focus
- Acceptance
- Focus note
- terminal-open 提示

### 4.3 停止新 plan 写入 observation/metrics

修改 `agent/infrastructure/plans/operations.py`：

- 删除 `record_observation()`。
- `create_plan()` 不再接收 `metrics` 参数。
- `update_meta()` 不再接收 `metrics` 参数。
- 新建 plan 不再初始化 `metrics` / `observations` 字段。
- 删除 `sync_current_metrics()` 调用。

不保留旧字段兼容：

- 默认不支持旧版本 `plan.json`。
- 旧 `plan.json` 中如果存在 `metrics` / `observations`，不需要迁移、不需要渲染、不需要测试兼容。
- 新逻辑只保证新 schema 下创建和更新的 plan 正常工作。
- 如果旧 session 因旧字段或旧 schema 行为异常，可以要求重新创建 plan。

### 4.4 清理模型 schema 与 helper

检查并清理：

- `agent/infrastructure/plans/model.py`
  - 不再为新 plan 强制补 `observations`。
  - 不再为新 plan 强制补 `metrics`。
  - 不为旧 plan 做 schema 迁移或兼容补全。
- `agent/infrastructure/plans/helpers.py`
  - 删除 `normalized_metrics()`、`sync_current_metrics()`，如果没有其他调用。
  - `plan_meta()` 删除 `observation_count` 和 `metrics`。
- `agent/infrastructure/tools/impl/__init__.py`
  - 删除 `plan_create` / `plan_update_meta` schema 中的 `metrics` 字段。

## 5. Compact Plan Summary 新格式

目标格式：

```text
Active plan summary:
- Plan: <title> (version <n>)
- Goal: <goal>
- Objectives: <first 3 objectives>
- Constraints: <first 3 constraints>
- Progress: completed=<n>, in_progress=<n>, blocked=<n>, pending=<n>, canceled=<n>
- Current focus: <step_id> - <title>
- Acceptance: <acceptance>
- Focus note: <note>
```

如果 active plan 已无未完成 step：

```text
Active plan summary:
- Plan: <title> (version <n>)
- State: open plan has no unfinished steps.
- Next: if the goal is satisfied, call plan_close; otherwise call plan_add_step for the next iteration.
```

不得包含：

- latest metrics
- latest observation
- hypothesis
- next action
- 模型生成的实验总结

## 6. Prompt 调整

修改 `agent/prompts.py`：

删除：

- `plan_record_observation` 能力说明。
- “After experiments, backtests, or validations, call plan_record_observation...”。
- “When long-term goals, constraints, or latest metrics change...” 中的 latest metrics 表述。

新增简短规则：

```text
Plan records task control state only. Do not use plan as factual memory.
When facts matter, re-read files, inspect command outputs, or rerun checks.
Keep step notes brief and operational; do not store experiment conclusions or metrics in notes.
```

保持提示词简洁，不新增长篇解释。

## 7. 测试计划

更新或新增测试：

### 7.1 Plan tool 注册

验证：

- `TOOLS` 中不包含 `plan_record_observation`。
- tool schema 中不包含 `plan_record_observation`。
- `plan_create` schema 不包含 `metrics`。
- `plan_update_meta` schema 不包含 `metrics`。

### 7.2 Compact summary

构造新 schema 的 active plan，验证：

- summary 不包含 `Latest metrics`。
- summary 不包含 `Latest observation`。
- summary 不包含 `Hypothesis`。
- summary 不包含 `Next action`。
- summary 仍包含 goal、progress、focus、acceptance。
- summary 不渲染 objective/constraint 中的 `current` 字段；如果测试数据中包含 `current`，也应忽略。

### 7.3 Plan flow

更新 `test/test_plan_tool.py`：

- 删除 `plan_record_observation` 相关测试。
- 删除 metrics/current sync 相关断言。
- 保留 create、add_step、update_meta、update_step、dependency、reorder、close 流程。

### 7.4 Prompt

新增或更新轻量测试，验证系统提示词：

- 不包含 `plan_record_observation`。
- 不包含要求记录 observation 的描述。
- 包含 “Plan records task control state only” 或等价短规则。

### 7.5 新 schema 字段

验证新建 plan：

- `plan.json` 不包含 `metrics`。
- `plan.json` 不包含 `observations`。
- `plan_meta()` 返回内容不包含 `metrics`。
- `plan_meta()` 返回内容不包含 `observation_count`。
- `plan_create` 不接受 `metrics` 参数。
- `plan_update_meta` 不接受 `metrics` 参数。

## 8. 死代码清理清单

实现后搜索并清理：

```bash
rg "plan_record_observation|record_observation|observations|Latest observation|Latest metrics|hypothesis|next_action|normalized_metrics|sync_current_metrics" agent test
```

处理原则：

- 与公开 observation 功能相关的代码删除。
- 与旧 plan 兼容读取相关的字段不保留。
- 如果某个 helper 只服务 metrics/observation，删除。
- 测试中的旧断言同步删除，不保留无效覆盖。

## 9. 验证命令

执行：

```bash
python -m compileall -q .
pytest test/test_plan_tool.py test/test_plan_context_summary.py -q
```

如果存在专门的 tool schema 测试，也一并执行。

## 10. 非目标

本次不做：

- 通用 artifact schema。
- 自动 metrics 抽取。
- observation source 校验。
- plan correction 机制。
- CLI 展示优化。
- 新增长期记忆系统。

这次只做硬切：plan 只保留任务控制状态。
