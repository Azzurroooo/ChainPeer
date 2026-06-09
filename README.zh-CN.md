<p align="center">
  <img src="assets/chainpeer.svg" alt="ChainPeer logo" width="104" />
</p>

<h1 align="center">ChainPeer Agent</h1>

<p align="center">
  一个精巧、标准、可恢复的 Python Agent 运行时，面向真实的本地编码工作流。
</p>

<p align="center">
  <a href="README.md">English</a> | 简体中文
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/Architecture-layered-success.svg" alt="Layered architecture" />
  <img src="https://img.shields.io/badge/Interface-CLI-informational.svg" alt="CLI interface" />
</p>

## ChainPeer 是什么？

ChainPeer 是一个标准 Python 版本的自主编码 Agent 实现。它既可以作为本地 CLI 工具直接使用，也希望成为一个足够清晰的参考样本：展示一个 Agent 运行时可以如何被拆解、组织、持久化和恢复。

这个项目的基本判断是：Agent 不必先成为庞大的框架，才能成为可靠的工具。ChainPeer 尽量保持结构清楚、工具契约克制、运行状态可追踪。从上下文压缩到工具执行，每个部件都以尽可能小的形式实现，同时不牺牲交互体验和工程可维护性。

## 设计理念

- **先做减法，再做加法**：优先减少概念、模块和隐式状态。只有当抽象确实降低复杂度时，才引入新的抽象。
- **小工具，清晰契约**：Shell、文件、网页、PDF、计划和技能等工具都通过紧凑接口暴露，返回结构尽量稳定可预测。
- **把上下文当作运行时状态**：上下文估算、自动压缩和工具结果归一化不是提示词附属品，而是运行时的核心职责。
- **本地优先，可持续恢复**：会话、消息、工具调用、压缩记录和元数据都以 append-only 的本地记录保存，便于中断后继续工作。
- **标准 Python，而非框架惯性**：项目使用普通 Python 模块、依赖倒置、异步编排和聚焦的服务层，避免把简单问题包裹进过重的框架。
- **默认好用，机制可见**：CLI 追求直接可用，同时在需要时展示模型、会话、工作目录、状态和诊断信息。

## 能力概览

- 交互式编码 Agent CLI，支持流式输出、斜杠命令、会话恢复、状态渲染和本地诊断。
- OpenAI 兼容的异步 Chat Client，支持配置模型、base URL、reasoning effort 和上下文窗口。
- 基于 JSONL 的 append-only 会话存储，记录消息、工具调用、压缩结果和会话元数据。
- 运行时上下文管理，包含预算估算、自动压缩、上下文长度救援和工具结果归一化。
- 基于 DAG 的计划工具，用于跨轮次追踪带依赖关系的任务。
- 内置 Shell、文件、网页、PDF、计划和技能发现等工具。
- FastAPI 会话适配器，便于在交互式 CLI 之外驱动运行时。

## 快速开始

### 环境要求

- Python 3.12+
- 一个 OpenAI 兼容 Chat Completion 端点的 API Key

### 安装

```bash
git clone https://github.com/Azzurroooo/ChainPeer.git
cd chainpeer

python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-runtime.txt
```

macOS 或 Linux:

```bash
source .venv/bin/activate
pip install -r requirements-runtime.txt
```

### 配置

ChainPeer 默认读取 `~/.chainpeer/settings.json`。也可以使用 `OPENAI_API_KEY`、`OPENAI_API_BASE`、`DEFAULT_MODEL` 等环境变量。

最小 `settings.json` 示例：

```json
{
  "model": "your-model-name",
  "apiKey": "your-api-key",
  "baseUrl": "https://api.openai.com/v1",
  "reasoningEffort": "high",
  "contextWindow": 258400,
  "effectiveContextWindowPercent": 95,
  "autoCompactEnabled": true
}
```

启动前可以先运行诊断：

```bash
python main.py --doctor
```

### 运行

```bash
python main.py
```

恢复最近一次本地会话：

```bash
python main.py -c
```

恢复指定会话：

```bash
python main.py --session <session-id>
```

## CLI 命令

| 命令 | 说明 |
| --- | --- |
| `python main.py` | 启动一个新的交互式 Agent 会话。 |
| `python main.py -c` | 恢复最近一次本地会话。 |
| `python main.py --session <id>` | 按 ID 恢复指定会话。 |
| `python main.py --debug` | 关闭流式输出，并显示更详细的运行时与工具诊断信息。 |
| `python main.py --doctor` | 检查本地配置，不需要有效 API Key。 |
| `python main.py --allow-unsafe-bash` | 允许执行默认安全策略会阻止的 Shell 命令。 |

在交互式 CLI 中，斜杠命令可用于诊断、会话管理、模型切换和状态查看。输入工具栏会展示当前会话、模型、工作目录和关键提示。

## 架构

ChainPeer 使用分层结构，并在运行时核心与基础设施适配器之间遵循依赖倒置。

```text
agent/
├── application/
│   ├── runtime/       # 异步运行时门面、turn runner、stream pump、工具调用处理
│   ├── services/      # 上下文管理、压缩、token 使用、技能选择
│   └── ports/         # Chat client、会话存储、工具注册表抽象
├── infrastructure/
│   ├── llm/           # OpenAI 兼容异步 Chat Client
│   ├── persistence/   # append-only 会话记录与仓储
│   ├── plans/         # DAG 计划模型、存储、调度和上下文注入
│   └── tools/impl/    # Bash、文件、网页、PDF、计划和技能工具
└── interfaces/
    ├── cli/           # 交互式 CLI、斜杠命令、状态 UI
    └── api/           # FastAPI 会话流式适配器
```

运行时与持久化边界见 [`docs/runtime-and-persistence.md`](docs/runtime-and-persistence.md)。

## 开发

安装开发依赖：

```bash
pip install -r requirements.txt
```

运行测试：

```bash
pytest test/ -q
```

测试覆盖运行时事件、上下文预算、压缩、会话持久化、恢复行为、工具结果归一化、计划、技能、CLI 渲染和斜杠命令。

## 展望

ChainPeer 关注的是：在保持足够简单、可读、可测试的前提下，Agent 系统还能走多远。后续探索会围绕三个方向展开：

- 如何让 Agent 的能力增长不必伴随过多机制膨胀。
- 如何探索 Agent 的全新呈现方式，让工作过程更可观察、更连续、更平静。
- 如何为 Python Agent 的通用设计提供更清楚的结构、边界和实现路径。

这个项目在形态上保持克制，但目标并不保守：它希望证明，一个有能力的 Agent 可以由简单部件、可见状态和清晰边界组成。

## 许可证

本项目基于 [MIT License](LICENSE) 发布。
