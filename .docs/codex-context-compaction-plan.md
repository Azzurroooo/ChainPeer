# Codex 可执行计划：Context 管理与压缩五步落地

## 目标

把当前“`session.chat_history` 既是持久化回放结果、又是直接喂给模型的上下文”的实现，升级成一套可控的上下文管理系统，分五步落地：

1. `ContextManager`
2. `ContextEstimator`
3. `rolling conversation summary`
4. `hot/warm/cold tool policy`
5. `context / compact` 命令

这份计划默认给 Codex 直接执行，目标是“小步可合并、不中断现有 CLI、兼容旧 session、失败可回退”。

---

## 当前代码现状

### 现状结论

当前仓库里，上下文链路仍然是强耦合的：

- [`agent/interfaces/cli/chat_cli.py`](e:\code\agent\agent_base\agent\interfaces\cli\chat_cli.py)
  `ChatCLI.start()` 里直接把 `self._session.chat_history` 赋给 `self.chat_history`，之后用户输入、assistant 输出、tool 消息都直接 append 到这一个列表。
- [`agent/application/runtime.py`](e:\code\agent\agent_base\agent\application\runtime.py)
  `process_user_turn()` 直接拿 `chat_history` 送给 `chat_client.create(...)`。
- [`agent/infrastructure/persistence/jsonl_session_store.py`](e:\code\agent\agent_base\agent\infrastructure\persistence\jsonl_session_store.py)
  `_load_session()` 负责从 `messages.jsonl + tool_calls.jsonl` 重建 `chat_history`；`resume_mode=summary` 只是对 tool result 做截断，不是真正的上下文预算与压缩。

### 核心问题

- “持久化历史” 和 “本轮喂模型上下文” 没有解耦。
- 没有统一的 token / char 预算估算器。
- 对普通对话没有滚动摘要能力。
- 对 tool 结果只有一刀切截断，没有冷热分层。
- 用户没有显式命令查看 / 触发压缩能力。

---

## 实施原则

- 不破坏已有 session 文件格式读取能力。
- 保留原始 `messages.jsonl` 与 `tool_calls.jsonl` 作为完整事实源。
- 新增的 summary / compact 信息优先放 sidecar 文件或新增字段，避免重写历史 JSONL 的高风险方案。
- 先做“可工作 + 可观测”，再做“更智能”。
- 每一步都必须带测试，且前一步完成后，后一步才能依赖它。

---

## 架构主线补充

为了避免把 Step 1 误解成终态，这里补充一条更明确的演进主线：

- 五步能力建设回答的是：系统最终需要哪些能力。
- `chat_history` 替代路线回答的是：现有代码怎样平滑迁移到这些能力，而不在中途把系统搞乱。

这两条线必须同时成立。

### `chat_history` 替代路线

最终目标不是“把 `chat_history` 改个名字继续用”，而是：

- `ContextManager` 成为唯一的送模上下文构建入口。
- 持久化层成为完整事实源。
- CLI / runtime 不再长期维护一份全量内存对话副本。
- 内存中只保留短生命周期的热区数据和当前回合临时状态。

建议把替代路线拆成四个阶段：

1. `Step 1A`：先把送模入口收口到 `ContextManager`。
2. `Step 1B`：给 `SessionStore` 增加按需读取接口，让 `ContextManager` 能从持久化层拿材料。
3. `Step 1C`：让 `ContextManager` 主要基于持久化数据拼接上下文，而不是依赖全量 `chat_history`。
4. `Step 1D`：把 CLI / runtime 中对全量 `chat_history` 的维护职责收掉，只保留热区缓存和未落盘状态。

后续 Step 2 到 Step 5 都应建立在这条替代路线之上，而不是继续默认 `chat_history` 永远存在。

---

## Step 1: ContextManager

### 目标

把“真正喂给模型的上下文”和 `chat_history` 脱钩，并为最终完全替代 `chat_history` 建立迁移骨架。

### 这一步要解决什么

当前 `chat_history` 同时承担三个职责：

- UI 展示历史
- session 恢复结果
- LLM 请求输入

这会让后续的预算控制、摘要替换、tool 热冷分层都很难安全落地。第一步必须先把“上下文构建”独立出来，但要明确：

- Step 1 的完成不等于 `chat_history` 已经可以删除。
- Step 1 只是把送模主路径从 `chat_history` 手里接出来。
- 后续还需要继续把“全量历史拥有权”迁移到 `ContextManager + SessionStore`。

### 设计原则

`ContextManager` 的长期职责应该是：

- 作为唯一送模入口
- 按需查询持久化事实源
- 拼接 system / recent / summary / tool context
- 输出模型真正看到的 `messages`

`ContextManager` 不应该长期持有一份无限增长的全量内存上下文。长期设计上，更推荐：

- `SessionStore` / persistence 负责保存完整事实源
- `ContextManager` 负责按需读取和拼接
- 内存里只保留最近热区、当前回合临时消息、最近一次 context snapshot

### Step 1 分阶段目标

#### Step 1A: 送模入口收口到 `ContextManager`

这是当前已经完成的最小实现：

- `runtime` 不再直接把 `chat_history` 送给模型。
- 改为调用 `ContextManager.build_messages(...)`。
- 第一版允许 `ContextManager` 做无损透传，保证行为不变。

#### Step 1B: 为“脱离 `chat_history`”准备持久化读取接口

这一小步是接下来必须补的，不然 `ContextManager` 只是换了个壳：

- 给 `SessionStore` 增加按需读取接口，而不是只暴露整块 `chat_history`。
- 推荐能力：
  - `get_system_message()`
  - `get_recent_messages(limit=...)`
  - `get_messages_slice(...)`
  - `get_tool_records(...)`
  - `get_latest_conversation_summary()`
  - `get_latest_context_snapshot()`
- 这些接口可以先基于现有 JSONL 读取实现，不要求一开始就高性能索引化。

#### Step 1C: `ContextManager` 主要改为“从持久化读取并拼接”

当 Step 1B 到位后，`ContextManager.build_messages(...)` 应逐步改成：

- 优先从 `SessionStore` 拉 system / recent / tool / summary 数据
- 只把当前回合尚未落盘的热区消息作为内存补丁拼进去
- 不再要求调用方传一个全量 `chat_history`

建议接口演进为：

```python
class ContextManager:
    def build_messages(
        self,
        session,
        pending_messages: list[dict] | None = None,
    ) -> ContextBuildResult:
        ...
```

这里的 `pending_messages` 只表示“尚未落盘、但本轮必须参与送模的少量临时消息”，不是完整历史。

#### Step 1D: 从 CLI / runtime 中移除全量 `chat_history` 拥有权

这是“完全替代 `chat_history`”真正完成的标志。目标状态应是：

- [`agent/interfaces/cli/chat_cli.py`](e:\code\agent\agent_base\agent\interfaces\cli\chat_cli.py) 不再维护全量 `self.chat_history`
- [`agent/application/runtime.py`](e:\code\agent\agent_base\agent\application\runtime.py) 不再接收全量历史列表
- session 恢复不再以“先重建整段 `chat_history` 再使用”为默认主路径
- UI 层需要展示历史时，单独从持久化层读取展示数据

到这一步，`chat_history` 可以：

- 要么完全删除
- 要么只作为兼容层字段保留，但不再是核心流程依赖

### 推荐数据边界

为了支持这条迁移路线，建议明确区分三类数据：

- `conversation_log`
  - 完整事实源，存于 `messages.jsonl` / `tool_calls.jsonl` / sidecar
- `pending_messages`
  - 当前回合尚未完全落盘、但需要送模的少量临时消息
- `model_context_messages`
  - `ContextManager` 最终构造出来、真正送给模型的上下文

后续实现中，不要再把这三类东西混成一个 `chat_history` 变量。

### 具体改动

#### Step 1A 已完成的最小改动

1. 新增 `ContextManager`，负责从 session / runtime 状态构造“本次请求 messages”。
2. `AgentRuntime.process_user_turn()` 不再直接把传入的 `chat_history` 全量交给 `chat_client.create(...)`。
3. 改成：
   - runtime 接收完整会话历史
   - 调用 `ContextManager.build_messages(...)`
   - 将 `build_result.messages` 送入模型
4. `chat_history` 仍然保留，继续作为：
   - 当前进程内完整对话事实链
   - 写入 session 的来源
5. 第一版 `ContextManager` 允许无损透传，以保证行为等价。

#### Step 1B 到 Step 1D 需要新增到计划中的改动

1. 扩展 `SessionStore`，增加按需读取上下文片段的接口。
2. 把 `JsonlSessionStore` 的“重建整段 `chat_history`”逻辑逐步拆成可查询片段接口。
3. 调整 `ContextManager`，让其主要依赖 `SessionStore` 读取，而不是依赖全量历史列表。
4. 调整 `ChatCLI`，让 UI 展示历史和送模上下文构建分离。
5. 调整 `runtime` 签名，逐步移除 `chat_history: list[dict]` 作为核心输入。
6. 最终只保留少量 `pending_messages` / hot zone 缓存在内存中。

### 推荐文件变更

#### Step 1A

- 新增 [`agent/application/services/context_manager.py`](e:\code\agent\agent_base\agent\application\services\context_manager.py)
- 可选新增 [`agent/application/ports/context_store.py`](e:\code\agent\agent_base\agent\application\ports\context_store.py)
- 修改 [`agent/application/runtime.py`](e:\code\agent\agent_base\agent\application\runtime.py)
- 必要时在 [`agent/bootstrap/container.py`](e:\code\agent\agent_base\agent\bootstrap\container.py) 注入依赖

#### Step 1B 到 Step 1D

- 修改 [`agent/application/ports/session_store.py`](e:\code\agent\agent_base\agent\application\ports\session_store.py)
- 修改 [`agent/infrastructure/persistence/jsonl_session_store.py`](e:\code\agent\agent_base\agent\infrastructure\persistence\jsonl_session_store.py)
- 修改 [`agent/interfaces/cli/chat_cli.py`](e:\code\agent\agent_base\agent\interfaces\cli\chat_cli.py)
- 按需要新增轻量 query helper，例如：
  - `agent/application/services/context_query.py`
  - 或 `agent/infrastructure/persistence/context_reader.py`

### 接口演进建议

#### 当前过渡接口

```python
class ContextManager:
    def build_messages(
        self,
        full_history: list[dict],
        session,
        pending_user_message: dict | None = None,
    ) -> ContextBuildResult:
        ...
```

#### 目标接口

```python
class ContextManager:
    def build_messages(
        self,
        session,
        pending_messages: list[dict] | None = None,
    ) -> ContextBuildResult:
        ...
```

### 验收标准

#### Step 1A

- 运行时真正发给模型的 `messages` 来源于 `ContextManager`，不再直接等于 `chat_history`。
- 当前功能行为不变：普通问答、tool call、多轮对话继续可用。
- 新接口可在不改 session 存储格式的前提下引入后续压缩能力。

#### Step 1B 到 Step 1D 完成后的额外验收标准

- `ContextManager` 构建上下文时，不再需要全量 `chat_history` 常驻内存。
- CLI / runtime 不再拥有完整历史副本。
- 上下文构建主要来自持久化层按需读取。
- 内存里只保留热区和 pending 状态。
- 删除或兼容保留 `chat_history` 字段都不会影响主流程。

### 测试

#### Step 1A

- 新增测试：`ContextManager` 在默认模式下输出与旧逻辑兼容的 messages。
- 新增测试：tool call 回合后，assistant/tool 消息顺序不变。
- 回归测试：CLI 多轮对话不因上下文构建层引入而丢消息。

#### Step 1B 到 Step 1D

- 新增测试：`ContextManager` 可仅基于 session 查询接口构建上下文。
- 新增测试：没有全量 `chat_history` 时，多轮对话仍可正常继续。
- 新增测试：session 恢复后不需要预先重建整段历史也能送模。
- 新增测试：CLI 展示历史与送模上下文来源分离后行为正确。
- 新增测试：长会话场景下内存中不再持有完整历史列表。

---
## Step 2: ContextEstimator

### 目标

先知道当前用了多少上下文、何时要压缩。

### 这一步要解决什么

在没有预算估算的情况下，后面的 summary 和冷热分层都只能拍脑袋。第二步先建立“估算”和“阈值决策”。

### 设计要求

新增一个估算器，例如：

- `agent/application/services/context_estimator.py`

第一版不要强依赖精确 tokenizer；可以采用分层估算：

1. 优先：如果当前 chat client 或模型适配器支持 token 估算，就用它。
2. 回退：用字符数 / 经验比率估算，例如：
   - `estimated_tokens ~= ceil(len(text) / 4)`

### 需要提供的能力

- 估算单条 message 大小
- 估算整段 messages 总大小
- 提供预算配置
- 提供压缩触发判断

建议定义：

```python
@dataclass
class ContextBudget:
    max_input_tokens: int
    reserve_output_tokens: int
    soft_limit_tokens: int
    hard_limit_tokens: int
```

```python
@dataclass
class ContextEstimate:
    message_count: int
    estimated_input_tokens: int
    estimated_chars: int
    over_soft_limit: bool
    over_hard_limit: bool
```

### 具体改动

1. 新增 `ContextEstimator`。
2. 在 `ContextManager.build_messages(...)` 里集成估算结果。
3. 在 `build_result.stats` / `build_result.decisions` 中记录：
   - 当前估算 token
   - 预算阈值
   - 是否需要 compact
4. 在 debug 模式下把预算信息打出来，便于观察。
5. 给 session 元数据或 sidecar 增加最近一次上下文构建统计快照，便于后续 `context` 命令读取。

### 推荐文件变更

- 新增 [`agent/application/services/context_estimator.py`](e:\code\agent\agent_base\agent\application\services\context_estimator.py)
- 修改 [`agent/application/runtime.py`](e:\code\agent\agent_base\agent\application\runtime.py)
- 修改 [`agent/infrastructure/persistence/jsonl_session_store.py`](e:\code\agent\agent_base\agent\infrastructure\persistence\jsonl_session_store.py)

### 配置建议

先把预算做成可配置项，放在 config 层或 session store 可读配置里：

- `context_max_input_tokens`
- `context_reserve_output_tokens`
- `context_soft_limit_ratio`

默认值可以保守一点，例如：

- `max_input_tokens = 24000`
- `reserve_output_tokens = 4000`
- `soft_limit = 0.75 * max_input_tokens`
- `hard_limit = max_input_tokens - reserve_output_tokens`

### 验收标准

- 每次请求前都能得出可读的上下文预算估算。
- 系统能判断“无需压缩 / 建议压缩 / 必须压缩”。
- 即使没有精确 tokenizer，也能稳定工作。

### 测试

- 新增测试：空历史 / 短历史 / 长历史的估算结果合理。
- 新增测试：超过 soft / hard limit 时标志位正确。
- 新增测试：tool 内容很大时，总量估算明显增加。

---

## Step 3: Rolling Conversation Summary

### 目标

只压缩旧对话，不碰最近热区。

### 这一步要解决什么

目前只有 tool result 截断，没有对普通 user/assistant 对话的滚动摘要。需要引入“旧对话摘要 + 最近消息保真”的双层上下文。

### 设计要求

新增 conversation summary 服务，例如：

- `agent/application/services/conversation_summary_service.py`

第一版建议把会话按三段处理：

- `hot`: 最近 N 轮 user/assistant/tool 完整保留
- `warm`: 中间区域可在必要时做轻量压缩
- `cold`: 更老历史折叠为 rolling summary

但在这一阶段，先只做“cold summary + hot recent”。

### 推荐策略

- 永远保留：
  - system message
  - 最近 `N` 轮对话
  - 最近一次未完成的 tool 交互链
- 仅对更老的 user/assistant 历史生成 summary
- summary 作为单独的一条 `assistant` 或 `system` 风格消息注入上下文，例如：

```text
Conversation summary so far:
- 用户正在重构 session/context 机制
- 已确认 chat_history 与模型输入强耦合
- 之前已完成 tool summary 方案草案
```

### 存储建议

不要覆盖原消息。

新增 sidecar 文件，例如：

- `conversation_summaries.jsonl`

每条记录可以包含：

```json
{
  "id": "summary_001",
  "kind": "rolling_conversation_summary",
  "covers_message_ids": ["...", "..."],
  "current_goal": "...",
  "progress_summary": "...",
  "important_facts": ["...", "..."],
  "important_decisions": ["...", "..."],
  "open_questions": ["...", "..."],
  "created_at": "...",
  "version": "1"
}
```

### Rolling Summary 字段设计

你提到的这几个字段方向是对的，而且确实比单一 `summary_text` 更利于 agent 续跑。这里建议采用“最小但够用”的字段集，不要一开始就做成很重的 memory schema。

### 推荐保留字段

- `current_goal`
  - 当前阶段用户真正想完成的目标，尽量写成一句话。
  - 用途：帮助 agent 快速知道“现在在做什么”，避免只看到旧历史却抓不到主任务。
- `progress_summary`
  - 到目前为止已经完成了什么、推进到了哪一步，1 到 3 句。
  - 用途：帮助 agent 判断下一步应该延续而不是重复劳动。
- `important_facts`
  - 与任务直接相关、后续可能继续引用的事实列表。
  - 只保留高价值事实，比如约束、现状、关键接口、已确认的行为，不要把普通聊天碎片塞进来。
- `important_decisions`
  - 已经明确拍板的方案、约束、取舍。
  - 用途：防止 agent 在长对话后反复推翻已有结论。
- `open_questions`
  - 还未决、但会影响下一步实现或设计的问题。
  - 用途：让 agent 知道哪里可以继续推进，哪里需要先确认。

### 建议新增两个轻量辅助字段

除了你列的五个，我建议再补两个很轻的字段，收益很高：

- `summary_text`
  - 一句到两句的自然语言总览。
  - 用途：给模型一个低成本入口，先快速读懂摘要，再看结构化字段。
- `covered_turns`
  - 标记这条 rolling summary 覆盖到哪个 turn 范围，例如 `{ "start": 1, "end": 12 }`。
  - 用途：帮助 `ContextManager` 判断哪些旧消息已被这条 summary 覆盖，避免重复喂入。

### 为什么不建议一开始再加更多字段

先不要加太多，比如：

- `risks`
- `next_steps`
- `blocked_by`
- `references`
- `confidence`

这些字段不是完全没用，但第一版容易让 summary 生成变复杂、稳定性下降，而且和现有字段有较大重叠：

- `progress_summary` 已经能覆盖部分 `next_steps`
- `open_questions` 已经能覆盖部分 `blocked_by`
- `important_facts` 和 `important_decisions` 已经能承接大部分长期信息

第一版控制在 7 个字段左右，更容易生成、验证、消费。

### 推荐最终 schema

建议 rolling conversation summary 第一版固定为：

```json
{
  "id": "summary_001",
  "kind": "rolling_conversation_summary",
  "covers_message_ids": ["...", "..."],
  "covered_turns": { "start": 1, "end": 12 },
  "summary_text": "用户正在推进 context compaction 方案，已确定五步实施顺序，当前聚焦 rolling summary 字段设计。",
  "current_goal": "完善 rolling summary schema，使其既轻量又足够支持 agent 续跑。",
  "progress_summary": "已经确定需要将模型输入上下文与 chat_history 脱钩，并规划了 estimator、rolling summary、tool 温度策略与 context/compact 命令。",
  "important_facts": [
    "当前 chat_history 与实际送模上下文仍强耦合",
    "resume_mode=summary 目前仅对 tool result 做截断",
    "rolling summary 只应压缩冷区，不碰最近热区"
  ],
  "important_decisions": [
    "rolling summary 采用 sidecar 持久化，不覆盖 messages.jsonl",
    "先做最小可用字段集，避免 schema 过重",
    "summary 生成失败不能影响主流程"
  ],
  "open_questions": [
    "最近热区按最近几条消息还是最近几个 user turn 来定义",
    "rolling summary 采用 lazy 生成还是 compact 命令显式生成优先"
  ],
  "created_at": "...",
  "version": "1"
}
```

### 生成约束

为了让这组字段真的好用，建议在 summary 生成 prompt 里加这些约束：

- `current_goal` 只写一个，不要变成列表。
- `progress_summary` 写“已经完成什么”，不要写泛泛总结。
- `important_facts` 只写事实，不写建议和猜测。
- `important_decisions` 只写已确认事项，不写候选方案。
- `open_questions` 只写真正未决、且影响后续动作的问题。
- 每个列表字段建议限制在 3 到 7 条。

### ContextManager 消费建议

`ContextManager` 在把 rolling summary 注入模型时，建议渲染成紧凑文本，而不是直接裸 JSON：

```text
Conversation summary:
- current_goal: 完善 rolling summary schema，使其既轻量又足够支持 agent 续跑
- progress_summary: 已完成 context compaction 五步规划，当前正在细化 rolling summary 字段设计
- important_facts:
  - chat_history 与实际送模上下文仍强耦合
  - rolling summary 只压缩冷区
- important_decisions:
  - 使用 sidecar 持久化
  - summary 失败不影响主流程
- open_questions:
  - 热区按消息数还是按 user turn 定义
```

这样既保留结构，又比 JSON 更容易被模型消费。

### 具体改动

1. 新增 summary 生成服务。
2. 在 `ContextManager` 中加入“冷区替换摘要”的拼装逻辑。
3. 先支持 lazy 生成：
   - 构建上下文时发现超预算且没有可用 rolling summary，则生成一次并持久化
4. summary 失败时回退：
   - 不影响正常对话
   - 仍可用原始消息 + 截断策略
5. 定义“最近热区”的判定规则，例如：
   - 最近 6 条非 system 消息
   - 或最近 3 个 user turn

### 推荐文件变更

- 新增 [`agent/application/services/conversation_summary_service.py`](e:\code\agent\agent_base\agent\application\services\conversation_summary_service.py)
- 修改 [`agent/application/services/context_manager.py`](e:\code\agent\agent_base\agent\application\services\context_manager.py)
- 修改 [`agent/infrastructure/persistence/jsonl_session_store.py`](e:\code\agent\agent_base\agent\infrastructure\persistence\jsonl_session_store.py)
- 可选新增 [`agent/infrastructure/llm/conversation_summary_client.py`](e:\code\agent\agent_base\agent\infrastructure\llm\conversation_summary_client.py)

### Codex 执行约束

- 不要对最近热区做摘要替换。
- 不要把 rolling summary 做成覆盖式写回 `messages.jsonl`。
- 不要要求 summary 生成阻塞主回答流。

### 验收标准

- 长对话时，冷区能被一条或少量 summary message 替代。
- 最近热区保持原文，不被压缩。
- summary 缺失或失败不影响会话继续进行。

### 测试

- 新增测试：长会话构建上下文时，会优先保留最近热区。
- 新增测试：冷区存在 summary 时，上下文体积下降。
- 新增测试：summary 失败时仍能回退到原始历史。

---

## Step 4: Hot / Warm / Cold Tool Policy

### 目标

最近 tool 结果高保真，旧 tool 结果走截断或已有摘要。

### 这一步要解决什么

当前 `resume_mode=summary` 只会把所有 tool result 做统一截断。我们需要把 tool 结果按时间和价值分层，而不是一刀切。

### 策略定义

建议定义三层 tool 温度：

- `hot`
  - 最近 1 到 3 次 tool call，或当前回合相关 tool call
  - 保留高保真内容
- `warm`
  - 还可能被引用，但已经不是最近交互核心
  - 保留结构化摘要，必要时附少量截断正文
- `cold`
  - 只保留摘要，或更强截断

### 推荐实现方式

在 `ContextManager` 中，不直接把所有 `role=tool` 内容原样拼进去，而是通过统一策略函数决定：

```python
def render_tool_message_for_context(tool_record: dict, temperature: str) -> str:
    ...
```

同时扩展 tool summary 持久化能力。可复用你现有 `.docs/context-summary-implementation-plan.md` 中的思路，但这里要升级成“带温度策略的 tool message 渲染”。

### 渲染优先级建议

1. `hot`
   - 优先完整原文
   - 若超大，则保留高保真截断版
2. `warm`
   - 优先 `summary_for_resume`
   - 无 summary 时走旧截断逻辑
3. `cold`
   - 只用 summary
   - 无 summary 时走更强截断

### 持久化建议

可新增：

- `tool_call_summaries.jsonl`

记录字段例如：

```json
{
  "call_id": "...",
  "tool_name": "read_file",
  "summary_for_resume": {...},
  "created_at": "...",
  "version": "1"
}
```

### 具体改动

1. 新增 tool temperature policy 模块，例如：
   - `agent/application/services/tool_context_policy.py`
2. 让 `JsonlSessionStore` 提供读取 tool summary sidecar 的能力。
3. 在 `ContextManager` 构建时，对 tool 消息分层渲染，而不是只依赖 `resume_mode`。
4. 保留 `resume_mode`，但把它从“唯一策略”降级为“fallback / override 配置”。
5. `resume_mode=full` 可作为调试保底模式继续存在。

### 推荐文件变更

- 新增 [`agent/application/services/tool_context_policy.py`](e:\code\agent\agent_base\agent\application\services\tool_context_policy.py)
- 修改 [`agent/application/services/context_manager.py`](e:\code\agent\agent_base\agent\application\services\context_manager.py)
- 修改 [`agent/infrastructure/persistence/jsonl_session_store.py`](e:\code\agent\agent_base\agent\infrastructure\persistence\jsonl_session_store.py)

### 验收标准

- 最近 tool result 比旧 tool result 保真度更高。
- summary 可用时优先使用 summary。
- 没有 summary 时仍能稳定退回旧截断逻辑。
- 不破坏 assistant `tool_calls` 的恢复顺序与语义。

### 测试

- 新增测试：最近 tool 结果使用 full 或高保真渲染。
- 新增测试：较旧 tool 结果优先使用 summary。
- 新增测试：没有 summary 时 warm/cold 仍可回退。
- 新增测试：不同温度下上下文总量显著不同。

---

## Step 5: `context` / `compact` 命令

### 目标

把能力暴露给用户。

### 这一步要解决什么

前四步完成后，如果用户不能观察和触发，上下文系统就不可控。第五步把能力暴露到 CLI。

### 命令设计

建议先实现两个本地命令，不走模型：

1. `context`
2. `compact`

### `context` 命令建议行为

打印当前上下文状态，例如：

- 当前 message 数
- 估算 token
- hot/warm/cold 各占多少
- 是否存在 rolling summary
- 最近一次 compact 是否生效

建议输出：

```text
Context status
- estimated_input_tokens: 14320
- soft_limit_tokens: 18000
- hard_limit_tokens: 20000
- recent_hot_messages: 8
- warm_tool_messages: 5
- cold_messages_compacted: 24
- rolling_summary_present: yes
```

### `compact` 命令建议行为

手动触发一次上下文压缩，行为可以是：

- 生成或刷新 rolling conversation summary
- 生成缺失的 tool summaries
- 重新计算 context snapshot
- 输出 compact 前后估算变化

### CLI 集成点

当前 CLI 在 [`agent/interfaces/cli/chat_cli.py`](e:\code\agent\agent_base\agent\interfaces\cli\chat_cli.py) 的 `_loop()` 里直接判断 `quit/exit/q`。建议在这里扩展本地命令分支：

- `context`
- `compact`
- 可选：`context full`
- 可选：`compact force`

这些命令应直接调用本地应用服务，不经过 LLM。

### 具体改动

1. 在 CLI 层新增本地命令解析。
2. 新增 application service，例如：
   - `agent/application/services/context_commands.py`
3. `context` 命令读取最近一次 `ContextManager` 构建统计；必要时实时重算。
4. `compact` 命令触发 summary / tool summary 生成，并返回结果文本。
5. debug 模式下可打印更详细决策信息。

### 推荐文件变更

- 修改 [`agent/interfaces/cli/chat_cli.py`](e:\code\agent\agent_base\agent\interfaces\cli\chat_cli.py)
- 新增 [`agent/application/services/context_commands.py`](e:\code\agent\agent_base\agent\application\services\context_commands.py)
- 修改 [`agent/bootstrap/container.py`](e:\code\agent\agent_base\agent\bootstrap\container.py)

### 验收标准

- 输入 `context` 能看到当前上下文预算和压缩状态。
- 输入 `compact` 能主动触发压缩并返回前后对比。
- 命令不经过模型，不消耗额外 LLM 调用。

### 测试

- 新增测试：CLI 输入 `context` 时不进入 runtime LLM 流程。
- 新增测试：CLI 输入 `compact` 时会触发 compact 逻辑。
- 新增测试：命令输出包含预算信息和压缩结果。

---

## 推荐实施顺序

按下面顺序提交，不要一口气大改：

1. 引入 `ContextManager`，先做无损透传。
2. 引入 `ContextEstimator`，先把预算和阈值跑通。
3. 接入 rolling conversation summary 的持久化与上下文替换。
4. 接入 hot/warm/cold tool policy。
5. 最后把 `context` / `compact` 暴露到 CLI。

每一步都单独可测、可提交、可回退。

---

## 建议模块划分

为避免单文件继续膨胀，建议新增以下文件，而不是把逻辑继续堆进 `jsonl_session_store.py` 或 `runtime.py`：

- `agent/application/services/context_manager.py`
- `agent/application/services/context_estimator.py`
- `agent/application/services/conversation_summary_service.py`
- `agent/application/services/tool_context_policy.py`
- `agent/application/services/context_commands.py`
- `agent/infrastructure/llm/conversation_summary_client.py`
- `agent/infrastructure/llm/tool_summary_client.py`

`jsonl_session_store.py` 只做：

- session 读写
- summary sidecar 读写
- 轻量数据适配

不要把复杂的上下文决策逻辑塞回 persistence 层。

---

## 建议 sidecar 文件

为了兼容现有 JSONL 设计，推荐新增 sidecar，而不是原地重写历史记录：

- `conversation_summaries.jsonl`
- `tool_call_summaries.jsonl`
- 可选：`context_snapshots.jsonl`

理由：

- 风险低
- 便于增量落地
- 兼容旧 session
- 不需要重写 `messages.jsonl` / `tool_calls.jsonl`

---

## 总体验收标准

全部五步完成后，应满足：

- `chat_history` 不再等于“实际送模上下文”。
- 每次送模前都能估算预算，并得出是否需要压缩。
- 旧对话可被 rolling summary 替换，最近热区保持原文。
- tool 结果按 hot/warm/cold 分层进入上下文。
- 用户可以通过 `context` / `compact` 观察和触发压缩。
- 旧 session 可继续读取。
- summary 缺失、失败、异常时，不影响基础对话和 tool 调用。

---

## 给 Codex 的直接执行指令

请按以下方式执行，不要跳步：

1. 先实现 `ContextManager`，但保持行为等价，补测试后再继续。
2. 再实现 `ContextEstimator` 和预算配置，把估算结果接入 `ContextManager`。
3. 再实现 rolling conversation summary，只压缩冷区，不碰最近热区。
4. 再实现 tool 的 hot/warm/cold policy，并优先复用已有 tool summary 思路。
5. 最后在 CLI 中加入 `context` / `compact` 本地命令。

执行约束：

- 保持向后兼容，不破坏已有 session。
- 优先新增模块，避免把 `runtime.py` 和 `jsonl_session_store.py` 继续做胖。
- 每一步都添加 success / fallback / failure path 测试。
- 如果某一步需要引入 LLM summary client，必须保证失败不影响主流程。
- 除非用户明确要求，否则不要在同一个 patch 里把五步一次性全部实现。

---

## 建议首批测试清单

- `test/test_context_manager.py`
- `test/test_context_estimator.py`
- `test/test_conversation_summary_service.py`
- `test/test_tool_context_policy.py`
- `test/test_context_commands.py`

至少覆盖：

- 成功路径
- 摘要缺失回退
- 摘要生成失败回退
- 超预算触发压缩
- 最近热区不被压缩
- tool 温度策略渲染差异
- `context` / `compact` 不走模型


