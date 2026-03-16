# Bash 安全机制重构计划

## 1. 现状与问题分析
当前 `bash` 工具的实现中，`allow_unsafe` 是作为一个参数直接暴露给 LLM 的。
- **问题**：如果 LLM 出现幻觉或被攻击，可以直接在调用 `bash` 时设置 `allow_unsafe=True`，从而绕过安全检查。这使得安全机制形同虚设。
- **改进方向**：`allow_unsafe` 不应作为单次命令执行的参数，而应作为 Agent 运行时的一个全局状态或配置。只有在明确切换到“不安全模式”后，才允许执行高风险命令。

## 2. 核心修改逻辑
我们将把“是否允许不安全命令”从**参数控制**改为**状态控制**。

### 2.1 修改目标
1.  **移除 `bash` 工具的 `allow_unsafe` 参数**：让 `bash` 只专注于执行命令，不再负责决策安全策略。
2.  **引入全局安全状态**：在 `tools/bash.py` 中维护一个 `_UNSAFE_MODE_ENABLED` 状态（默认为 False）。
3.  **新增 `set_bash_safety_mode` 工具**：允许 Agent 显式地请求切换安全模式。这增加了一个操作步骤，使得进入不安全模式成为一个有意识的、可被审计的动作。

## 3. 详细实施步骤

### 步骤 1: 修改 `tools/bash.py`
1.  **新增全局变量**：
    ```python
    _UNSAFE_MODE_ENABLED = False
    ```
2.  **新增 `set_bash_safety_mode` 函数**：
    - 接受参数 `enabled: bool`。
    - 修改 `_UNSAFE_MODE_ENABLED` 的值。
    - 返回状态切换成功的消息。
3.  **修改 `bash` 函数**：
    - 移除 `allow_unsafe` 参数。
    - 在内部检查 `_is_dangerous_command(command)`。
    - 逻辑变更：
        - 如果命令危险 **且** `_UNSAFE_MODE_ENABLED` 为 `False`：**拦截并报错**。提示用户或 Agent 需要先调用 `set_bash_safety_mode(True)`。
        - 如果命令危险 **且** `_UNSAFE_MODE_ENABLED` 为 `True`：**放行执行**。
        - 普通命令：直接执行。

### 步骤 2: 修改 `tools/schemas.py`
1.  **更新 `bash` 工具定义**：
    - 删除 `parameters` 中的 `allow_unsafe` 字段。
2.  **注册新工具 `set_bash_safety_mode`**：
    - 定义如下：
      ```json
      {
        "name": "set_bash_safety_mode",
        "description": "设置 Bash 工具的安全模式。开启不安全模式 (enabled=True) 后，将允许执行 rm -rf 等高风险命令。请谨慎使用。",
        "parameters": {
          "type": "object",
          "properties": {
            "enabled": {
              "type": "boolean",
              "description": "是否开启不安全模式 (True=允许危险命令, False=禁止)"
            }
          },
          "required": ["enabled"]
        }
      }
      ```

## 4. 预期行为流程
1.  **场景 A：默认状态下执行危险命令**
    - Agent 调用：`bash(command="rm -rf ./temp")`
    - 结果：**Block**。返回 Error："Potentially dangerous command blocked. Unsafe mode is disabled. Use set_bash_safety_mode(True) to override."

2.  **场景 B：Agent 主动切换模式**
    - Agent 调用：`set_bash_safety_mode(enabled=True)`
    - 结果：**Success**。返回 "Bash unsafe mode enabled. Dangerous commands are now allowed."

3.  **场景 C：切换后执行危险命令**
    - Agent 调用：`bash(command="rm -rf ./temp")`
    - 结果：**Execute**。命令被执行。

## 5. 安全性收益
- **防误触**：Agent 不会因为一次错误的参数生成就执行危险命令。
- **意图明确**：必须显式调用切换工具，表明 Agent "知道自己在做什么"。
- **可审计**：在日志中可以清晰看到 `set_bash_safety_mode` 的调用记录，作为风险操作的标记。
