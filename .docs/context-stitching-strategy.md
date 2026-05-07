# Context 拼接策略详解（动态压缩版）

本文用于解释当前 Agent 在不同运行场景下如何拼接最终 `context.messages`，以及何时进行对话压缩、何时进行工具截断。

## 1. 核心目标

- 在不丢失关键语义的前提下控制输入窗口。
- 优先保留“最新且最有行动价值”的信息（热对话 + 热工具结果）。
- 把压缩行为做成自动化、可观测、可复用。

## 2. 默认预算与估算方法

默认预算来自 `ContextBudget`：

- `hard_limit_tokens = 32000`
- `system_budget_tokens = 2000`
- `conversation_budget_tokens = 6000`
- `tool_budget_tokens = 20000`

估算采用快速近似：`tokens ~= chars / 4`。

## 3. 每轮拼接主流程

每次 `build_messages()` 都按固定顺序执行：

1. 读取持久化消息 `persisted_messages`。
2. 叠加当前轮 `pending_messages`。
3. 先执行工具策略（温度分类 + 预算截断）。
4. 做首次估算（system/conversation/tool 三类 token）。
5. 若纯对话超预算，执行冷对话压缩。
6. 清理内部字段（例如 `_tool_temperature`）。
7. 产出 `ContextSnapshot`、`stats`、`decisions` 并持久化。
8. 返回 `messages` 给 runtime 调用模型。

## 4. 工具消息拼接策略

### 4.1 温度分类

工具调用会按批次划分温度：

- `hot`：最新批次，优先保真。
- `warm`：中间批次，摘要化展示。
- `cold`：更旧批次，极简展示。

### 4.2 Hot 优先预算分配

工具预算不按原消息顺序消耗，而是先排序后渲染：

1. 收集工具消息 `call_id` 顺序。
2. 按温度排序 `hot > warm > cold`（同温度保持先后顺序）。
3. 按排序顺序渲染并扣减 `remaining_tool_chars`。
4. 将结果回填到原消息时间线中。

这样可以确保预算紧张时，最新 hot 工具内容优先保留。

### 4.3 截断规则

- `available_chars is None`：不做预算截断。
- `available_chars <= 0`：直接返回空字符串（严格不超预算）。
- 内容超限：保留前缀并追加提示：
  `...(Output truncated due to context limits. Please use search/grep tools to find specific content)...`

## 5. 对话压缩策略

### 5.1 热区与冷区

- 热区：最近 `hot_message_limit` 条非 system 消息，始终保留。
- 冷区候选：不在热区，且满足：
  - `role` 为 `user` 或 `assistant`
  - 不含 `tool_calls`
  - `content` 有效非空

### 5.2 触发条件

仅当 `conversation_tokens >= conversation_budget_tokens` 时触发压缩。

注意：工具超预算本身不会触发对话摘要。

### 5.3 步长复用

若已有历史摘要，且新增冷消息数量未达到阈值 `summary_step_threshold`，则复用旧摘要，避免每轮重算。

### 5.4 拼接方式

- 在冷区首次位置插入 `summary_message`。
- 被摘要覆盖的冷消息跳过。
- 未覆盖的新冷消息保留。
- system 与热区消息保持原样。

## 6. 典型场景与结果

### 场景 A：预算均未超限

- 结果：不做对话摘要、不做工具预算截断。
- 输出：`system + 对话原文 + 按温度渲染后的工具消息`。

### 场景 B：仅工具超预算

- 结果：工具执行 Hot 优先截断；对话不压缩。
- 输出：对话完整，低优先级工具可能缩短或清空。

### 场景 C：仅对话超预算

- 结果：触发冷对话摘要；工具正常按温度渲染。
- 输出：`system + summary + 新冷消息 + 热区消息 + 工具消息`。

### 场景 D：工具和对话都超预算

- 结果：双通道同时治理：
  - 对话侧：冷区摘要
  - 工具侧：Hot 优先截断

### 场景 E：摘要可复用

- 结果：不重算摘要，仅复用旧摘要并保留新冷消息。
- 价值：降低每轮压缩开销。

### 场景 F：工具预算耗尽

- 结果：后续工具消息内容可为空字符串。
- 价值：严格守住预算边界，不出现“预算外附加文本”。

## 7. 可观测性（排障抓手）

每轮都会持久化 context 快照，关键字段：

- `stats`：
  - `system_tokens` / `conversation_tokens` / `tool_tokens`
  - `pre_compaction_*`
  - `cold_compacted_message_count`
  - `hot_tool_message_count` / `warm_tool_message_count` / `cold_tool_message_count`
- `decisions`：
  - `over_conversation_budget`
  - `over_tool_budget`
  - `over_system_budget`
  - `rolling_summary_applied`
  - `rolling_summary_generated`
  - `over_hard_limit`

runtime debug 中可直接看到：

- `conversation_over`
- `tool_over`
- `hard`

## 8. 当前边界（按现状保留）

- `over_system_budget` 目前仅做标记，不做自动治理（按当前决策保留）。
- token 估算为工程近似（`chars / 4`），偏重性能与稳定。

## 9. 代码定位

- 拼接编排：`agent/application/services/context_manager.py`
- 工具温度与截断：`agent/application/services/tool_context_policy.py`
- 分项预算估算：`agent/application/services/context_estimator.py`
- runtime 调试输出：`agent/application/runtime.py`

## 10. 一句话总结

当前实现是“双通道动态治理”：

- 对话通道按 `conversation_budget` 做步长摘要；
- 工具通道按 `tool_budget` 做 Hot 优先截断；

并在保持消息时间线稳定的前提下，最大化保留当前轮最关键上下文。
