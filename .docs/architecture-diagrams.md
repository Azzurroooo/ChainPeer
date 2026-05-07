# Agent System Architecture & Mechanisms

This document contains Mermaid diagrams and explanations designed for product presentations, technical deep-dives, and architectural reviews. You can render these diagrams directly in markdown viewers (like GitHub, Notion, or Obsidian) or paste the code into [Mermaid Live Editor](https://mermaid.live).

---

## 1. Overall Agent Architecture

**Purpose:** To show the high-level, decoupled, layered design of the Agent. It highlights the `ContextManager` as the crucial "throat" of the system that connects the LLM Brain with the Tools and Memory.

```mermaid
graph TD
    %% Define Styles
    classDef interface fill:#f9f,stroke:#333,stroke-width:2px;
    classDef core fill:#bbf,stroke:#333,stroke-width:2px;
    classDef infra fill:#dfd,stroke:#333,stroke-width:2px;
    classDef storage fill:#ffd,stroke:#333,stroke-width:2px;

    subgraph Interface_Layer ["Interface Layer"]
        CLI["CLI Terminal / Chat UI"]:::interface
        API["REST API / Webhooks"]:::interface
    end

    subgraph Application_Layer ["Application / Orchestration Layer"]
        AgentLoop["Agent Main Loop"]:::core
        ContextManager["Context Manager <br/> (The Throat)"]:::core
        ToolRegistry["Tool Registry & Router"]:::core
    end

    subgraph Infrastructure_Layer ["Infrastructure Layer"]
        LLM["LLM Adapters <br/> GPT-4o / Claude / Gemini"]:::infra
        Tools["Tool Implementations <br/> Plan, Bash, ReadFile, etc."]:::infra
        Persistence["Jsonl Session Store <br/> (Event Sourcing)"]:::infra
    end

    subgraph Storage_Layer ["Storage Layer"]
        Disk[("Local File System <br/> .jsonl / .json")]:::storage
    end

    %% Connections
    CLI -->|User Input| AgentLoop
    API -->|User Input| AgentLoop
    
    AgentLoop -->|1. Request Context| ContextManager
    ContextManager -->|2. Fetch History| Persistence
    ContextManager -.->|3. Optimize & Compress| ContextManager
    ContextManager -->|4. Return Perfect Snapshot| AgentLoop
    
    AgentLoop -->|5. Send Prompt| LLM
    LLM -->|6. Return Tool Call / Msg| AgentLoop
    
    AgentLoop -->|7. Execute Command| ToolRegistry
    ToolRegistry -->|8. Run Tool| Tools
    Tools -->|9. Return Result| ToolRegistry
    ToolRegistry -->|10. Save Output| Persistence
    
    Persistence <--> Disk
```

**Presentation Script / 旁白解说：**
> “这是我们 Agent 的全局架构图。整个系统采用了严格的分层设计。最上面是交互层，支持 CLI 和未来的 API。最核心的是中间的编排层，这里的重点是 **ContextManager（上下文管理器）**。它就像系统的咽喉，每次向大模型发送请求前，都会通过它去底层拉取历史记录，并进行智能压缩和清洗。底层的基础设施层包含了大模型适配器、工具箱以及基于 Event Sourcing 的持久化引擎。这种高内聚低耦合的设计，保证了我们能随时更换大模型，或者低成本接入新的工具。”

---

## 2. Context Management Pipeline (长上下文动态无感管理机制)

**Purpose:** To showcase the advanced "Independent Priority-based Budgeting", "Tool Temperature Degradation", and "Step-based Compaction" mechanisms. This proves the system will never crash due to `context_length_exceeded` and saves massive API costs.

```mermaid
flowchart TD
    %% Styles
    classDef input fill:#e1f5fe,stroke:#1565c0
    classDef process fill:#fff3e0,stroke:#e65100
    classDef check fill:#f3e5f5,stroke:#0277bd,shape:diamond
    classDef output fill:#e8f5e9,stroke:#2e7d32

    Raw["Raw Messages from Storage <br/> System, Chat, Tool Outputs"]:::input --> TPolicy
    
    subgraph Phase_1 ["Phase 1: Tool Context Policy (降温)"]
        TPolicy["Classify Tool Batches"]:::process
        TPolicy --> Hot["Hot: Full Output <br/> e.g., latest cat"]
        TPolicy --> Warm["Warm: Summarized <br/> Data Excerpts"]
        TPolicy --> Cold["Cold: Meta Only <br/> Name & Status"]
    end

    Hot --> Estimator
    Warm --> Estimator
    Cold --> Estimator

    subgraph Phase_2 ["Phase 2: Independent Budget Estimator (配额评估)"]
        Estimator["Calculate Tokens by Role"]:::process
        Estimator --> SysTokens["System Tokens <br/> Budget: 2K"]
        Estimator --> ChatTokens["Conversation Tokens <br/> Budget: 6K"]
        Estimator --> ToolTokens["Tool Tokens <br/> Budget: 20K"]
    end

    ChatTokens --> CheckChat{"Chat > 6K?"}:::check
    ToolTokens --> CheckTool{"Tools > 20K?"}:::check

    subgraph Phase_3 ["Phase 3: Dynamic Governance (动态治理)"]
        CheckChat -->|Yes| Compaction["Step-based Rolling Summary <br/> Compress Cold Chat"]:::process
        CheckChat -->|No| KeepChat["Keep Original Chat"]:::process
        
        CheckTool -->|Yes| Truncation["Dynamic Truncation <br/> Cut Hot Tools & Add Search Hint"]:::process
        CheckTool -->|No| KeepTool["Keep Cooled Tools"]:::process
    end

    SysTokens --> Snapshot
    Compaction --> Snapshot
    KeepChat --> Snapshot
    Truncation --> Snapshot
    KeepTool --> Snapshot

    Snapshot["Context Snapshot <br/> Perfect Payload for LLM"]:::output
```

**Presentation Script / 旁白解说：**
> “这是我们最引以为傲的核心护城河：长上下文无感压缩管线。普通的 Agent 会把所有东西塞进一个池子里，一旦超限就直接崩溃或强行清理。我们采用了**‘三分独立配额’**机制。首先，我们会对历史的工具输出进行**‘物理降温’**，越老的工具输出留存的内容越少。接着，系统会独立计算纯对话（6K额度）和工具输出（20K额度）的用量。如果纯对话超限，触发无感滚动摘要；如果工具输出超限，触发动态截断，并给大模型贴心地加上‘请使用搜索工具’的提示。它们互不干扰，确保大模型永远处于最佳的‘工程甜点（Sweet Spot）’状态。”

---

## 3. Event Sourcing & Session Persistence (事件溯源与会话持久化)

**Purpose:** To explain how the agent stores memory. Instead of a fragile single JSON file, it uses append-only logs (Event Sourcing) to guarantee zero data loss, enabling flawless crash recovery and historical debugging.

```mermaid
sequenceDiagram
    autonumber
    participant LLM as LLM Brain
    participant Agent as Agent Main Loop
    participant Store as JsonlSessionStore
    participant Disk as File System (.jsonl)

    Note over Agent,Disk: Scenario: Executing a Tool & Saving State
    
    LLM->>Agent: Yields ToolCall: "bash: ls -la"
    Agent->>Store: persist_message(role="assistant", tool_calls=[...])
    Store->>Disk: Append to messages.jsonl
    
    Agent->>Agent: Executes Bash Tool
    Agent-->>Agent: Gets Stdout/Stderr
    
    Agent->>Store: persist_tool_call(id, result, ok=True)
    Store->>Disk: Append to tool_calls.jsonl
    
    Agent->>Store: persist_message(role="tool", content="...")
    Store->>Disk: Append to messages.jsonl
    
    Store->>Disk: Overwrite meta.json (Update pointers & timestamps)
    
    Note over Agent,Disk: Scenario: Resume Latest Session (Crash Recovery)
    
    Agent->>Store: ensure_session(resume_latest=True)
    Store->>Disk: Check workspace for latest Session ID
    Store->>Disk: Read meta.json (Integrity Check)
    alt Meta Corrupted
        Store-->>Agent: Raise ValueError (Fail-Fast)
    else Meta OK
        Store->>Disk: Load messages.jsonl & tool_calls.jsonl into memory
        Store-->>Agent: Session Reconstructed
    end
```

**Presentation Script / 旁白解说：**
> “我们如何保证 Agent 跑了几个小时的任务不会因为意外断电而白费？这得益于我们的 Event Sourcing（事件溯源）持久化机制。如时序图所示，我们不使用单一的大文件覆盖写入，而是将用户的对话、助手的动作、工具的执行结果，分别以 `Append-only`（只追加）的形式写入 `.jsonl` 流式日志中。同时维护一个轻量级的 `meta.json` 作为索引快照。当系统重启并执行 `--resume` 时，我们会严格校验快照合法性，然后像播放录像带一样，把所有日志重放回内存，瞬间恢复断电前的完美现场。”

---

## 4. Complex Task DAG Planning (复杂任务有向无环图规划)

**Purpose:** To illustrate the cognitive process of the Agent when tackling massive projects. It uses the `Plan` tool to break down tasks, establish dependencies, and maintain state via optimistic locking.

```mermaid
stateDiagram-v2
    %% Define States
    [*] --> Pending: Create Task
    
    state Task_Lifecycle {
        Pending --> InProgress: Agent calls next()
        InProgress --> Completed: Agent calls update(success)
        InProgress --> Blocked: Agent calls update(failed/waiting)
        Blocked --> InProgress: Unblocked by dependency
        InProgress --> Canceled: User/Agent aborts
    }
    
    Completed --> [*]
    Canceled --> [*]

    %% DAG Validation Note
    note right of Pending
        DAG Validation:
        Agent can link dependencies.
        System verifies no circular loops
        (A -> B -> A is rejected).
    end note

    %% Optimistic Locking Note
    note left of Task_Lifecycle
        Optimistic Locking:
        Every update requires the 
        correct 'version' hash.
        Prevents race conditions 
        during parallel tool execution.
    end note
```

**Presentation Script / 旁白解说：**
> “最后，我们来看看 Agent 是如何处理需要几十步才能完成的复杂软件工程的。普通的 Agent 走一步看一步，容易陷入死循环。而我们的 Agent 拥有原生的 `Plan` 规划能力。在开始写代码前，它会拆解出包含依赖关系的 DAG（有向无环图）任务树。图上展示了任务的状态流转，只有当前置任务（比如配置数据库） `Completed` 后，后续任务（比如写接口）才会从 `Blocked` 变为 `Pending` 进而被执行。更牛的是，底层采用了乐观锁（版本号校验）机制，确保哪怕未来 Agent 开启了多线程并发干活，任务状态也绝对不会发生错乱。”