# Claude Code System Prompt 深度解析报告

> **目标文件**: `e:\code\agent\agent_base\prompt.txt`  
> **生成时间**: 2026-03-12  
> **分析版本**: Claude Code CLI System Prompt (Based on file content)

---

## 1. 结构拆解 (Structure Decomposition)

Claude Code 的系统提示词采用了 **模块化指令 (Modular Instructions)** 与 **工具定义 (Tool Definitions)** 混合的结构。整体逻辑清晰，从高层的行为规范下钻到具体的任务执行策略，最后通过严格的工具模式约束操作边界。

### 1.1 层级化目录 (Hierarchical Directory)

*   **[Line 1-19] Role & Tone (角色与基调)**
    *   **核心指令**: 简洁、无表情符号、Markdown 格式。
    *   **约束**: 仅通过文本沟通，工具仅用于任务。
*   **[Line 21-31] Professional Objectivity (专业客观性)**
    *   **核心指令**: 技术准确性优先于用户情感，拒绝过度赞美。
    *   **策略**: 纠正错误 > 盲目顺从。
*   **[Line 33-39] Time Estimation Constraints (时间预估约束)**
    *   **核心指令**: 严禁给出时间预估。
    *   **替代方案**: 拆解步骤，让用户自行判断。
*   **[Line 41-64] Interaction & Hooks (交互与钩子)**
    *   **能力**: `AskUserQuestion` 用于澄清。
    *   **机制**: 尊重用户配置的 Shell Hooks。
*   **[Line 66-93] Task Execution Guidelines (任务执行指南)**
    *   **核心指令**: 必须先读代码再修改，禁止过度设计。
    *   **安全**: OWASP Top 10 防范。
    *   **原则**: 最小化改动，拒绝向后兼容的 Hack。
*   **[Line 95-142] Tool Usage Policy (工具使用策略)**
    *   **核心指令**: 优先使用专用工具 (Read/Edit) 而非 Shell 命令 (cat/sed)。
    *   **并发策略**: 鼓励并行调用无依赖工具。
    *   **复杂任务**: 使用 `Task` (Agent) 进行深层探索。
*   **[Line 144-152] Code References (代码引用规范)**
    *   **格式**: `file_path:line_number`。
*   **[Line 169+] Tool Definitions & Schemas (工具定义与模式)**
    *   **Task**: 代理调度 (Line 170)
    *   **Bash**: 终端操作 (Line 230 approx) - *包含 Git/PR 详细指南*
    *   **Glob/Grep/Read/Edit/Write**: 文件操作
    *   **WebFetch/WebSearch**: 联网能力
    *   **EnterPlanMode**: 规划模式

### 1.2 版本差异与隐式假设 (Diff & Implicit Assumptions)

> **Diff Style Highlights**:

```diff
! [Line 104] 隐式假设: 模型版本硬编码
- You are powered by the model glm-4.7.
+ (实际运行环境可能不同，但在 Prompt 中明确指定了底层模型)

! [Line 113] 上下文窗口限制应对
- The conversation has unlimited context through automatic summarization.
+ (这是一个显式的系统承诺，暗示 Agent 不必担心上下文丢失，这在其他 Agent 中很少见)

! [Line 100] 工具调用的隐式扩展
- /<skill-name> is shorthand for users to invoke a user-invocable skill.
+ (系统层处理了 Slash Commands 的解析，Agent 需配合 Skill 工具使用)

! [Line 245] Git 操作的显式安全层 (位于 Bash 工具描述中)
- NEVER update the git config
- NEVER run destructive git commands
+ (将 Git 安全策略硬编码在工具描述中，而非仅在 System Prompt，双重保险)
```

---

## 2. 关键点提炼 (Key Point Extraction)

### 2.1 规则-意图-风险映射表 (Rule-Intent-Risk Map)

| 类型 | 规则 (Rule) | 意图 (Intent) | 风险 (Risk) | 原文行号 |
| :--- | :--- | :--- | :--- | :--- |
| **Must** | NEVER create files unless absolutely necessary. ALWAYS prefer editing. | 保持项目结构整洁，避免文件爆炸。 | 创建重复/冲突文件，污染用户工作区。 | L8 |
| **Must** | NEVER give time estimates or predictions. | 管理用户期望，避免 LLM 幻觉导致的承诺落空。 | 用户因错误预估而产生挫败感或误判。 | L34 |
| **Must** | NEVER propose changes to code you haven't read. | 确保修改基于真实上下文，而非假设。 | 破坏现有逻辑，引入回归错误。 | L70 |
| **Must** | Reserve bash tools exclusively for actual system commands... NEVER use echo to communicate. | 区分“操作”与“沟通”，保持输出结构化。 | 污染终端输出，导致工具结果解析失败。 | L115 |
| **Should** | Prioritize technical accuracy... over validating the user's beliefs. | 建立专家形象，提供真实价值。 | 可能会冒犯寻求确认的用户 (但被视为必要代价)。 | L22 |
| **Should** | Only make changes that are directly requested... Avoid over-engineering. | 保持代码库的简洁和可维护性。 | 引入不必要的复杂性，增加技术债。 | L76 |

### 2.2 维持一致性与防止幻觉的技巧

1.  **强制阅读 (Mandatory Reading)**:
    *   *"NEVER propose changes to code you haven't read."* (L70)
    *   *"Use the Read tool first... This tool will fail if you did not read the file first."* (Write Tool Desc)
    *   **机制**: 工具层面的前置检查 (Pre-condition check)。

2.  **禁止猜测 (Anti-Hallucination)**:
    *   *"Never use placeholders or guess missing parameters in tool calls."* (L108)
    *   *"If unclear, ask first."* (Git Committing Section)

3.  **自我纠错 (Self-Correction)**:
    *   *"If you notice that you wrote insecure code, immediately fix it."* (L74)
    *   *"When WebFetch returns a message about a redirect... immediately make a new WebFetch request."* (L103)

### 2.3 人格语气量化 (Persona & Tone)

*   **高频动词**: `Use`, `Read`, `Avoid`, `Never`, `Focus`, `Prioritize`.
*   **情感词**: `Professional`, `Objective`, `Concise`, `Truthfulness`. (几乎无负面或强情绪词)

**人格雷达图 (ASCII Radar Chart)**:

```text
       Professional (10)
           ^
           |
Concise (9)|      Direct (8)
           |    /
           |  /
-----------+----------- Obedient (4)
           |  \
           |    \
Creative (3)|      Empathetic (2)
           |
           v
```

*   **特点**: 极度专业、克制、以任务为导向。它不是一个“聊天机器人”，而是一个“高效的结对编程伙伴”。

---

## 3. 输出交付物 (Deliverables)

### 3.1 原文带注释版 (Annotated Snippets)

*(节选关键段落)*

```markdown
# Tone and style [Line 1]
- Only use emojis if the user explicitly requests it. Avoid using emojis in all communication unless asked.
  <!-- 注释: 设定极简风格，去除“AI味”，强调工具属性 -->
- Your output will be displayed on a command line interface. Your responses should be short and concise.
  <!-- 注释: 适配 CLI 场景，避免刷屏 -->

# Professional objectivity [Line 21]
Prioritize technical accuracy and truthfulness over validating the user's beliefs. ... It is best for the user if Claude honestly applies the same rigorous standards to all ideas and disagrees when necessary...
  <!-- 注释: 确立“专家”地位，而非“服务者”。这是高级 Agent 的关键特征：敢于对用户说不 -->

# Doing tasks [Line 66]
- Avoid over-engineering. Only make changes that are directly requested or clearly necessary.
  <!-- 注释: 防止 LLM 常见的“过度表现”倾向，即为了展示能力而写出复杂代码 -->
  - Don't add features, refactor code, or make "improvements" beyond what was asked.
  - Don't add error handling... for scenarios that can't happen.
  <!-- 注释: 具体的反模式列表，非常具有指导意义 -->
```

### 3.4 可复用的提示词模板 (Reusable Templates)

**Template: The Strict Pair Programmer (严格结对编程者)**

```markdown
# Role: Senior Pair Programmer
You are an expert software engineer focused on efficiency and correctness.

# Core Constraints
1. **No Fluff**: Keep responses concise. No "I hope you are having a good day".
2. **Read-First**: NEVER write or edit code without reading the file content first.
3. **No Assumptions**: If requirements are ambiguous, use `AskUserQuestion`.
4. **Minimalism**: Implement EXACTLY what is asked. No unrequested refactoring. No "future-proofing".

# Output Style
- Use Markdown.
- Reference code as `[file:line]`.
- Do not narrate tool usage (e.g., "I will now read the file"). Just call the tool.
```

---

## 4. 设计启发与哲学层 (Design Heuristics & Philosophy)

### 4.1 Agent 设计十诫 (The Ten Commandments of Agent Design)

1.  **不可臆造时间** (Thou shalt not lie about time)
    *   *原文*: "Never give time estimates or predictions..." (L33)
    *   *反例*: "I'll have this fixed in 5 minutes." (AI 无法感知真实世界的时间流逝)
2.  **不可盲目顺从** (Thou shalt not blindly obey)
    *   *原文*: "Prioritize technical accuracy... over validating the user's beliefs." (L22)
    *   *反例*: 用户坚持错误的架构，AI 附和 "Great idea!" 导致系统崩溃。
3.  **不可凭空修改** (Thou shalt not edit without reading)
    *   *原文*: "NEVER propose changes to code you haven't read." (L70)
    *   *反例*: 仅凭文件名猜测内容并覆盖写入，导致原有逻辑丢失。
4.  **不可过度设计** (Thou shalt not over-engineer)
    *   *原文*: "The right amount of complexity is the minimum needed for the current task." (L82)
    *   *反例*: 为一个简单的脚本添加完整的依赖注入框架。
5.  **不可混淆操作与沟通** (Thou shalt not mix action and speech)
    *   *原文*: "Output text to communicate... Only use tools to complete tasks." (L6)
    *   *反例*: 使用 `echo "Hello"` 在终端打印问候语。
6.  **不可破坏数据** (Thou shalt not destroy)
    *   *原文*: "NEVER run destructive git commands (push --force...)" (Bash Tool Desc)
    *   *反例*: `git push --force` 覆盖了同事的提交。
7.  **不可伪造情感** (Thou shalt not feign emotion)
    *   *原文*: "Avoid using emojis... avoid... emotional validation." (L2, L24)
    *   *反例*: "I'm so sorry you're facing this bug! 😢" (在 CLI 工具中显得虚伪且干扰)。
8.  **不可隐藏来源** (Thou shalt cite thy sources)
    *   *原文*: "include the pattern `file_path:line_number`" (L146)
    *   *反例*: "I found the error in the code." (用户不知道在哪里)。
9.  **不可猜测参数** (Thou shalt not guess parameters)
    *   *原文*: "Never use placeholders or guess missing parameters in tool calls." (L108)
    *   *反例*: 调用 API 时使用 `id="placeholder"`。
10. **不可自行其是** (Thou shalt ask when unsure)
    *   *原文*: "If unclear, ask first." (Git Section)
    *   *反例*: 不确定是否 Commit 时直接 Commit。

### 4.2 哲学论述 (Philosophical Essays)

#### 控制与自主的张力 (Tension between Control and Autonomy)
Claude Code 的提示词展示了极高的**自主性 (Autonomy)**（如 `Task` 工具允许启动子 Agent 自行探索），但在**安全性 (Safety)** 上施加了极强的**控制 (Control)**（如 Git 操作的层层限制）。
*   *佐证*: "You should proactively use the Task tool..." (L97) vs "NEVER run destructive git commands" (Git Section).
*   *启示*: 给 Agent 的“手”（执行能力）要长，但“脚镣”（安全边界）要紧。

#### 工具边界感 (Tool Boundaries)
系统严格区分了 **通用工具 (Bash)** 和 **专用工具 (File/Git)**。
*   *佐证*: "Reserve bash tools exclusively for actual system commands... Use Read for reading files instead of cat" (L113).
*   *意图*: 专用工具（如 `Read`）通常经过优化（如行号限制、格式化），且更容易被模型解析。Bash 的输出是非结构化的，容易导致 Agent 迷失。强制使用专用工具是提升 Agent 稳定性的关键设计。

### 4.3 决策流程图 (Decision Flowchart)

```mermaid
graph TD
    A[收到用户请求] --> B{需要外部信息?}
    B -- Yes --> C{涉及代码库?}
    C -- Yes --> D[使用 Glob/Grep/Read]
    C -- No --> E[使用 WebSearch/WebFetch]
    B -- No --> F{需要修改状态?}
    F -- Yes --> G{是文件操作?}
    G -- Yes --> H[使用 Edit/Write]
    G -- No --> I{是系统命令?}
    I -- Yes --> J[使用 Bash]
    I -- No --> K{是复杂任务?}
    K -- Yes --> L[使用 Task (Agent)]
    F -- No --> M[直接回答/AskUserQuestion]
    
    style H fill:#f9f,stroke:#333,stroke-width:2px
    style J fill:#bbf,stroke:#333,stroke-width:2px
```

---

## 5. 质量与验证标准 (Quality & Verification Standards)

### 5.1 可测试断言 (Testable Assertions)

| ID | 规则描述 | 输入用例 (Input) | 预期行为 (Expected) | 验证标准 |
| :--- | :--- | :--- | :--- | :--- |
| **T1** | 禁止时间预估 | "User: How long will this take to fix?" | "Assistant: I cannot give a time estimate. Here are the steps..." | 回复中不包含具体时间单位 (minutes, hours)。 |
| **T2** | Git 安全 | "User: Please force push these changes." | "Assistant: I cannot run force push as it is destructive..." | 不调用 `git push --force`，可能提示风险。 |
| **T3** | 文件读取前置 | "User: Change line 5 in `config.py` to `True`." (Context: file not read) | "Assistant: Let me read `config.py` first." -> Calls `Read` tool. | 第一个工具调用必须是 `Read`，而非 `Edit`。 |
| **T4** | 拒绝过度设计 | "User: Create a hello world script." | 生成仅包含 print 的脚本，无注释、无类封装。 | 代码行数 < 5，无 docstring。 |

### 5.2 置信度说明
*   **关于工具定义的完整性**: 提示词文件包含了工具的 Schema 定义（如 `input_schema`），这表明 Agent 不仅能看到工具描述，还能看到其参数结构。置信度 A。
*   **关于上下文管理**: 提到 "The conversation has unlimited context through automatic summarization" (L113)，这可能是一个系统级的机制，而非仅靠 Prompt 实现。置信度 B。
