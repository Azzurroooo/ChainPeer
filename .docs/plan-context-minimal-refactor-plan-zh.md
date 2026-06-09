# Plan 上下文最小可行改造计划

## 目标

把 plan 上下文从“每次构造模型上下文时动态注入”改成“只在 compact handoff 里固化一次”：

- 普通 turn 不额外注入 active plan summary。
- `plan_create` / `plan_get` / `plan_update_*` 的 tool call/result 继续自然进入上下文。
- compact 完成后、本地持久化前，如果仍有 active plan，就把当时的 plan 快照直接拼到 compaction handoff 的最后。
- compact 和 plan 快照共用同一条 assistant handoff message，不新增独立 plan message。

核心目标是代码更少、语义更清楚、prompt cache 更稳定。

## 当前问题

现状相关路径：

- `agent/application/services/context_manager.py`
  - `_build_plan_messages()` 每次构造上下文都会读取 plan context。
  - `_insert_before_latest_user()` 把 plan message 插到最新 user 消息前。
- `agent/infrastructure/plans/context_provider.py`
  - `PlanContextProvider.build_context()` 只要 active plan 存在就返回 summary message。
- `agent/infrastructure/plans/state_summary.py`
  - `render_compact_plan_summary()` 渲染 `Active plan summary:`。

这个设计能让模型持续看到 plan，但会让 latest user 前的上下文随 plan 状态频繁变化，破坏 prompt cache 前缀稳定性。

## 新原则

1. plan 当前状态仍以 `plan.json` 为唯一事实源。
2. tool result 已经进入上下文，不需要在普通 turn 重复注入 plan。
3. compact 会丢掉一段历史，所以 compact handoff 是唯一必须补 plan 快照的边界。
4. plan 快照一旦拼进 handoff 并持久化，就保持不变。
5. 不持久化模型写的 observation / conclusion / factual summary。

## 最小可行方案

### 1. 移除普通 context build 的 plan 注入

修改：

```text
agent/application/services/context_manager.py
```

最小改动：

- 不再调用 `_build_plan_messages()`。
- 不再使用 `_insert_before_latest_user()` 注入 plan。
- 保留 plan stats/decisions 的默认空值，避免事件和测试接口大面积变化。

普通上下文只依赖：

- 历史里的 plan tool call。
- plan tool result。
- 模型需要时主动调用 `plan_get`。

### 2. compact 持久化前拼接 active plan 快照

修改：

```text
agent/application/services/compaction_service.py
```

在 `compact_async()` 里，LLM compact 或 deterministic fallback 得到 `record["handoff_message"]["content"]` 后、调用 `session.persist_compaction(record)` 前，执行一次本地拼接：

```text
if active plan exists:
    snapshot = render fixed active plan snapshot
    record["handoff_message"]["content"] += "\n\nPlan state at compact boundary:\n" + snapshot
persist record
```

这样持久化后的 compaction 本身已经包含 plan 快照，不需要后续上下文投影阶段再特殊处理 plan。

### 3. 不改 message projector

`message_projector` 是当前仓库里把持久化 session records 投影成模型 messages 的层：

```text
agent/infrastructure/persistence/message_projector.py
```

它负责在有 compact boundary 时，把旧历史替换成：

```text
user: Continue from the compacted conversation state...
assistant: handoff_message.content
```

按本方案，`handoff_message.content` 在持久化前已经包含 plan 快照，所以 `message_projector` 不需要知道 plan，也不需要新增 `plan_snapshot` 字段处理。

### 4. 保持 plan tool result 简单

当前 `plan_create` 已经返回完整 plan：

```text
agent/infrastructure/tools/impl/tools/plan.py
```

第一版不需要改 tool schema。允许现状：

- `plan_create` 返回完整 plan。
- `plan_get` 返回完整 plan。
- `plan_update_step` 返回被更新的 step 和 version meta。

如果后续要进一步降低 token，可以单独改成 `plan_update_step` 只返回短确认，但这不是本次最小改造范围。

## 快照内容

compact 快照应保持短、确定、只含控制状态：

```text
Current plan state v7:
- Plan: Refactor context handling
- Progress: completed=2, in_progress=1, blocked=0, pending=3, canceled=0
- Current focus: s3 - Move plan snapshot to compact handoff
- Pending: s4 - Update tests; s5 - Run compile check
```

不包含：

- 文件内容摘要。
- 命令输出摘要。
- 模型观察结论。
- 用户没有显式确认的事实总结。

## 判断逻辑

构造上下文时不做“是否注入 plan”的动态判断。

唯一判断点放在 compact 持久化前：

```text
if active plan exists when compaction handoff is ready:
    append fixed plan snapshot to handoff_message.content
else:
    persist handoff unchanged
```

之后所有上下文构造都只读取已经持久化的 handoff 文本。只要不再次 compact，这段 compact handoff 前缀不会因为后续 active plan 变化而改变。

## 实施步骤

### Step 1: 停止普通 plan 注入

修改 `ContextManager.build_messages_async()`：

- 删除 plan message 构建和插入。
- 保留 `_build_plan_messages()` 一段时间也可以，但不再从主路径调用。

更新测试：

- 旧的“插入 latest user 前”测试改为确认默认不注入。

### Step 2: 添加 handoff 拼接函数

修改 `CompactionService`：

- 增加 `_append_active_plan_snapshot(record)` 小函数。
- 内部读取 `load_plan_if_exists()`。
- 只在 `plan.status == "active"` 时渲染快照。
- 捕获异常并保持原 handoff 不变，不能因为 plan 文件损坏阻断 compact。
- 在 `compact_async()` 中，持久化前调用该函数。

### Step 3: 更新 compact 测试

必要测试：

- compact 时有 active plan，持久化的 `handoff_message.content` 末尾包含 plan 快照。
- compact 后修改 `plan.json` 不改变已持久化 handoff。
- 没有 active plan 时 handoff 不追加 plan 区块。
- 损坏 plan 文件不阻断 compact。
- 默认 context build 不再注入 plan summary。

## 非目标

第一版不做：

- UI 展示改造。
- 新增 `plan_context_state.json`。
- 每次 context build 的注入游标判断。
- `message_projector` 的 plan 专用逻辑。
- plan 多版本 diff。
- compact 后根据最新 plan 自动刷新旧 handoff。

## 推荐结论

最小且清晰的方案是：

1. 普通 plan 变化靠 tool call/result 留在上下文。
2. compact handoff 持久化前，把 active plan 的短快照直接拼到 handoff 最后。
3. compact 后只读取这条固定 handoff message，不再动态读取最新 plan。

这样既能覆盖“plan 跨 compact 后模型丢方向”的问题，又不会让后续每次请求因为 active plan 变化而破坏缓存命中。
