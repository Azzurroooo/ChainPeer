# 🤖 ChainPeer Agent

![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![Architecture](https://img.shields.io/badge/Architecture-Hexagonal-success.svg)
![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)

A highly robust, context-aware, and production-ready Autonomous Coding Agent. Designed with a clean hexagonal architecture, it features **Event Sourcing for session persistence**, a **DAG-based task planner**, and an innovative **Dynamic Context Budgeting** system to manage infinite context streams seamlessly.

---

## ✨ Why ChainPeer?

Most open-source agents suffer from two fatal flaws: they crash when tool outputs are too large, and they lose state if interrupted. ChainPeer solves this with enterprise-grade engineering:

- 🧠 **Infinite Context Illusion**: Utilizes a "Three-Tier Budget" (System/Conversation/Tools). Massive tool outputs are dynamically truncated (Hot/Warm/Cold), and long conversations are transparently summarized in the background. You never hit the `ContextLengthExceeded` wall.
- 💾 **Event Sourcing & Fail-Safe Resume**: Every message and tool output is appended to a `.jsonl` stream. You can hit `Ctrl+C` anytime. Run `python main.py -c` and the agent will reconstruct its memory exactly where you left off.
- 🗺️ **DAG Task Planning**: The agent doesn't just guess the next step. It builds a Directed Acyclic Graph (DAG) for complex tasks, executes them with optimistic locking, and blocks dependent tasks until prerequisites are met.
- 🏗️ **Hexagonal Architecture**: Beautifully decoupled. The `application` layer (brains) is strictly separated from the `infrastructure` layer (hands). Swapping LLM providers or storage engines requires zero changes to the core logic.

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.12+
- An OpenAI-compatible API key

### 2. Installation
```bash
git clone https://github.com/your-username/chainpeer.git
cd chainpeer

# Create and activate a virtual environment
python -m venv venv
source venv/Scripts/activate  # On Windows
# source venv/bin/activate    # On Mac/Linux

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the root directory:
```env
OPENAI_API_KEY=your_api_key_here
# Optional: Use an alternative API base (e.g., DeepSeek, Claude via proxy)
# OPENAI_API_BASE=https://api.deepseek.com/v1 
```

### 4. Run the Agent
```bash
python main.py
```

---

## 🛠️ CLI Usage

ChainPeer comes with a powerful CLI interface for managing sessions and debugging.

| Command | Description |
|---|---|
| `python main.py` | Start a brand new agent session. |
| `python main.py -c` | **Resume** the latest session from your local `.jsonl` storage. |
| `python main.py --session <ID>` | Resume a specific session by its ID. |
| `python main.py --debug` | Run in debug mode. Displays raw tool inputs/outputs and detailed context stats without streaming. |
| `python main.py --allow-unsafe-bash` | Allow the agent to execute potentially dangerous shell commands. |

Inside the interactive CLI, run `/doctor` for a local setup check covering Python, Git, settings, API key state, model, context window, session storage, and shell detection. Run `/sessions` to list recent local sessions before resuming one with `python main.py --session <id>`. Use `/model set <model>` to switch the default model and the active session model.

---

## 🏗️ Architecture at a Glance

ChainPeer strictly follows the Dependency Inversion Principle.

```text
agent/
├── application/       # The Brain: Context Management, Tool Execution routing, Budget Estimators.
│   ├── services/      # Core logic (e.g., ContextManager, ToolContextPolicy)
│   └── ports/         # Abstract Interfaces (ChatClient, SessionStore)
├── infrastructure/    # The Hands: API calls, File I/O, OS interactions.
│   ├── llm/           # OpenAI Client implementation
│   ├── persistence/   # Jsonl Session Store (Event Sourcing)
│   └── tools/impl/    # Tool logic (Bash, File Ops, Plan DAG)
└── interfaces/        # The Face: CLI, Web UI (Future)
```
*(For detailed Mermaid architecture diagrams, check the `.docs/architecture-diagrams.md` file.)*

---

## 🔧 Core Tools Built-in

The agent is equipped with a powerful arsenal of tools to interact with your codebase:

- **`plan`**: Creates, updates, and tracks DAG-based task trees.
- **`bash`**: Executes shell commands with robust timeout, cwd awareness, and auto-fallback decoding for Windows `gbk`/`utf-8` issues.
- **`file_ops`**: Reads, edits, and creates files.
- **`web`**: Fetches and parses web pages for documentation and search.

---

## 🧪 Testing

We believe in reliable agents. Run the test suite:
```bash
pytest test/ -q
```
*(Includes rigorous tests for Context Budgets, Tool Truncation, and Event Sourcing resume logic).*

---

## 🤝 Contributing

We welcome contributions! Please follow our `feat:`, `fix:`, `refactor:` commit conventions. Keep single Python files compact (<= 400 lines preferred). 

When adding new tools, ensure you define the interfaces in `application/ports` and implement the messy details in `infrastructure/tools`.

---

## 📄 License

MIT License. See `LICENSE` for details.
