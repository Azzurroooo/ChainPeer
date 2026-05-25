# Read / Grep / Glob 工具修缮计划

## 1. 背景

当前文件探索主要依赖 `list_files`、`grep`、`read_file`：

- `list_files` 适合看目录结构，但不适合按模式定位文件。
- `grep` 直接返回匹配行，容易把大量低价值内容带入上下文。
- `read_file` 虽有 `offset/limit`，但实现上仍会一次性读取完整文件。

参考 `src` 下 Claude Code 的实现，目标不是禁止完整读取，而是让默认路径变成：

```text
glob 定位文件 -> grep 定位内容 -> read_file 局部读取
```

完整文件读取仍应保留，用于小文件、配置文件、入口文件或确实需要整体理解的场景。

## 2. 目标

1. 新增独立 `glob` 工具，用于快速按文件名或路径模式定位文件。
2. 优化 `grep`，支持更省上下文的输出模式和分页。
3. 优化 `read_file`，改为真正的局部读取，并在结果中提供分页提示。
4. 更新工具 schema 与系统提示词，引导模型优先使用 `glob -> grep -> read_file`。
5. 增加 focused tests，保证行为稳定。
6. 清理修改后不再使用的旧逻辑或重复提示。

## 3. 非目标

- 不引入复杂索引系统。
- 不做语义搜索或向量检索。
- 不重写工具执行框架。
- 不改变 `edit_file`、`write_file` 的核心行为。
- 不禁止 `read_file` 读取完整小文件。
- 不新增与权限确认、安全策略无关的产品化功能。

## 4. 设计原则

- 工具职责清晰：
  - `list_files`：目录概览。
  - `glob`：按路径模式找文件。
  - `grep`：按内容找文件或匹配行。
  - `read_file`：读取具体文件的具体范围。
- 默认结果尽量短，但给模型明确的下一步参数。
- 保持实现轻量，优先使用 Python 标准库。
- 不为少数场景引入大型依赖。
- 所有工具输出继续使用 `tool_ok` / `tool_error`。

## 5. 实施步骤

### 5.1 新增 `glob` 工具

修改文件：

- `agent/infrastructure/tools/impl/tools/file_ops.py`
- `agent/infrastructure/tools/impl/tools/__init__.py`
- `agent/infrastructure/tools/impl/__init__.py`

新增函数：

```python
def glob(pattern: str, path: str = ".", max_results: int = 100, offset: int = 0) -> str:
    ...
```

行为要求：

- `path` 必须存在且为目录。
- `pattern` 使用 `pathlib.Path.rglob` 或 `glob` 风格匹配。
- 返回相对路径列表或文件条目数组，避免输出绝对路径浪费 token。
- 返回文件大小信息，至少包含 `size_bytes`；如果实现上更方便，也可以返回 `size_label`，方便模型判断是否需要全文读取。
- 默认最多返回 100 条。
- 支持 `offset` 分页。
- 自动跳过常见噪声目录，如 `.git`、`node_modules`、`.venv`、`__pycache__`、`dist`、`build`。
- 返回 meta：

```json
{
  "path": "...",
  "pattern": "**/*.py",
  "files": [
    {"path": "src/a.py", "size_bytes": 1234},
    {"path": "src/b.py", "size_bytes": 5678}
  ],
  "count": 100,
  "truncated": true,
  "next_offset": 100
}
```

实现建议：

- 增加一个共享 helper 判断路径是否应跳过，例如 `_is_skipped_path(path: Path) -> bool`。
- 不复用 `list_files` 的树形输出逻辑。
- 不输出图标，保持机器可读。
- 如果实现代价很低，也可以让 `list_files` 保持 size 信息，并在提示词里把它作为判断全文读与否的依据。

### 5.2 优化 `grep`

修改函数签名：

```python
def grep(
    pattern: str,
    path: str = ".",
    glob_pattern: str = "**/*",
    case_sensitive: bool = False,
    max_results: int = 50,
    output_mode: str = "files_with_matches",
    offset: int = 0,
    context: int = 0,
) -> str:
    ...
```

支持的 `output_mode`：

- `files_with_matches`：默认，只返回匹配文件路径。
- `content`：返回匹配行，包含文件、行号、文本。
- `count`：返回每个文件的匹配数量。

行为要求：

- 非法 `output_mode` 返回 `tool_error(..., "InvalidOutputMode")`。
- `files_with_matches` 默认只输出文件列表，避免大规模匹配行污染上下文。
- `content` 模式才返回匹配文本。
- `count` 模式返回 `{file, count}` 列表。
- 支持 `offset/max_results` 分页。
- 分页按当前 `output_mode` 的输出项计算：
  - `files_with_matches`：按匹配文件分页。
  - `content`：按匹配行分页。
  - `count`：按有匹配的文件计数项分页。
- `context > 0` 仅在 `content` 模式下生效，返回命中行附近上下文。
- 返回 meta 中包含：

```json
{
  "pattern": "...",
  "path": "...",
  "glob_pattern": "...",
  "output_mode": "files_with_matches",
  "matches": 50,
  "truncated": true,
  "next_offset": 50
}
```

实现建议：

- 继续使用现有 Python regex 实现，暂不强制依赖系统 `rg`。
- 内部先按文件聚合结果，再根据 `output_mode` 渲染。
- 避免为了 `files_with_matches` 收集所有匹配行；找到首个匹配即可记录文件。
- 大文件继续跳过，并可在 meta 中记录 `skipped_large_files` 数量。

### 5.3 优化 `read_file`

修改文件：

- `agent/infrastructure/tools/impl/tools/file_ops.py`

行为要求：

- 不再使用 `readlines()` 一次性读取完整文件。
- 使用流式读取，只保留请求范围内的行。
- `offset` 最小为 1。
- `limit` 设置合理上限，建议最大 2000；超过则截断到 2000 或返回参数错误，优先选择截断并在 meta 标明。
- 本轮保留大文件保护，但只拒绝“无范围的完整读取”或明显过大的请求；如果用户明确给出较小的 `offset/limit`，允许对超过 10MB 的文本文件做受限局部读取。本轮目标是避免 `readlines()` 全量加载，而不是把大文件完全禁掉。
- 返回内容保持行号格式。
- 返回 meta：

```json
{
  "file_path": "...",
  "offset": 1,
  "limit": 1000,
  "shown_start": 1,
  "shown_end": 1000,
  "total_lines": 3500,
  "truncated": true,
  "next_offset": 1001
}
```

实现建议：

- 对于普通文本文件，可单次遍历计算 `total_lines`，同时收集目标范围。
- 保留大文件保护：完整读取大文件仍应拒绝，但明确的局部读取请求可以通过。
- 错误信息应明确提示使用 `grep`、`glob`、更小范围，或先缩小 `limit`。

### 5.4 更新工具 schema

修改文件：

- `agent/infrastructure/tools/impl/__init__.py`

要求：

- 将 `glob` 加入 `TOOLS`。
- 为 `glob` 添加 schema meta。
- 更新 `grep` 的参数说明：
  - 增加 `output_mode` 枚举说明。
  - 增加 `offset`。
  - 增加 `context`。
- 更新 `read_file` 的参数说明：
  - 强调适合读取具体文件范围。
  - 说明大文件应先 `glob/grep` 定位。

### 5.5 更新工具导出

修改文件：

- `agent/infrastructure/tools/impl/tools/__init__.py`

要求：

- 从 `file_ops.py` 导出 `glob`。
- 加入 `__all__`。

### 5.6 更新系统提示词

修改文件：

- `agent/prompts.py`

最小改动：

- 在能力列表中加入 `glob`。
- 将文件探索流程改成：

```text
list_files for overview
glob for file pattern discovery
grep for content search
read_file with offset/limit for targeted reading
```

- 删除或改写与新工具冲突的旧表述。
- 保留“完整读取小文件是允许的”这一隐含能力，不写成禁止规则。
- 明确给出文件大小的软阈值建议，而不是硬性禁令。例如：
  - 小文件：可直接全文读。
  - 中等文件：优先按需读取，视任务决定是否全文读。
  - 大文件：先定位，再分区读。
- 阈值建议可写成参考值，不必绝对强制，例如：
  - `<= 20KB`：通常可直接全文读。
  - `20KB ~ 50KB`：灰区，优先看任务复杂度与上下文余量。
  - `>= 50KB`：优先定位后局部读取。
- 这些阈值应作为默认经验规则，而不是硬性限制；模型仍可在必要时全文读取更大的文件。

### 5.7 测试

新增测试文件：

- `test/test_file_navigation_tools.py`

覆盖：

1. `glob` 能按模式返回文件。
2. `glob` 跳过 `.git`、`node_modules` 等噪声目录。
3. `glob` 支持 `max_results/offset` 分页。
4. `grep` 默认 `files_with_matches` 只返回文件路径。
5. `grep(output_mode="content")` 返回匹配行和行号。
6. `grep(output_mode="count")` 返回每个文件的匹配数量。
7. `grep` 非法 regex 返回 `InvalidRegex`。
8. `grep` 非法 `output_mode` 返回 `InvalidOutputMode`。
9. `read_file` 支持 offset/limit，并返回 `next_offset`。
10. `read_file` 对超出范围 offset 返回 `OffsetOutOfRange`。
11. schema 中包含 `glob`，且 `grep.output_mode` 有枚举说明。

运行命令：

```bash
python -m compileall -q .
python test/test_file_navigation_tools.py
pytest test/test_file_navigation_tools.py -q
```

如果仓库中 pytest 环境不完整，至少保证单文件脚本测试和 compileall 通过。

## 6. 死代码与重复逻辑清理

实施完成后检查：

- `_build_tree` 只服务 `list_files`，不要让 `glob` 复用或污染它。
- 路径跳过逻辑如果在 `grep` 和 `glob` 中重复，应抽出一个小 helper。
- 删除 schema 或 prompt 中过时的“只用 list_files + grep”表述。
- 不保留未使用的中间 helper。
- 不引入未使用 import。

## 7. 验收标准

- `glob` 可用于按模式定位文件，输出短且可分页。
- `glob` 或 `list_files` 能提供文件大小，供模型判断是否全文读取。
- `grep` 默认输出文件列表，不再默认塞入大量匹配行。
- 需要内容时，`grep(output_mode="content")` 能返回准确行号。
- `read_file` 不再全量 `readlines()`，完整读取大文件受限，局部读取更省内存。
- 系统提示词包含小文件/中等文件/大文件的软阈值建议，但不把阈值写成硬禁令。
- 工具 schema 和系统提示词一致。
- 新增测试通过。
- 没有无关功能改动。
- 没有新增冗长模块或复杂抽象。

## 8. 建议提交信息

```text
feat(tools): refine file discovery and targeted reads
```
