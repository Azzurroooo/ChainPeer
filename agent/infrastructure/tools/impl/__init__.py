"""Default tool implementations and generated schemas."""

from __future__ import annotations

from typing import Any, Callable

from .core import build_tool_schemas
from .tools import (
    bash,
    bash_output,
    edit_file,
    fetch_web_page,
    grep,
    kill_shell,
    list_files,
    plan_close,
    plan_create,
    plan_get,
    plan_link_dependency,
    plan_next,
    plan_reorder,
    plan_update_step,
    read_file,
    read_pdf,
    search_web,
    skill_create,
    write_file,
)

TOOLS: dict[str, Callable] = {
    "read_file": read_file,
    "read_pdf": read_pdf,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_files": list_files,
    "grep": grep,
    "bash": bash,
    "bash_output": bash_output,
    "kill_shell": kill_shell,
    "plan_create": plan_create,
    "plan_get": plan_get,
    "plan_update_step": plan_update_step,
    "plan_link_dependency": plan_link_dependency,
    "plan_reorder": plan_reorder,
    "plan_next": plan_next,
    "plan_close": plan_close,
    "skill_create": skill_create,
    "search_web": search_web,
    "fetch_web_page": fetch_web_page,
}

_TOOL_SCHEMA_META: dict[str, dict[str, Any]] = {
    "read_file": {
        "description": "读取文本文件内容，支持行号和分页读取。Agent应通过此工具查看代码上下文。",
        "param_descriptions": {
            "file_path": "文件绝对或相对路径",
            "offset": "起始行号（默认 1）",
            "limit": "最多读取的行数（默认 1000 行，避免大文件超出上下文）",
        },
    },
    "read_pdf": {
        "description": "解析PDF文件内容，支持文字版和扫描版PDF。提取结构化文本（标题、段落）、表格（Markdown格式）。分页返回，每次最多30页。扫描版PDF自动使用OCR。",
        "param_descriptions": {
            "file_path": "PDF文件路径",
            "start_page": "起始页码（默认1）",
            "end_page": "结束页码（默认到文件末尾，每次最多30页）",
            "force_ocr": "强制使用OCR（用于编码异常的文字PDF，默认False）",
        },
    },
    "write_file": {
        "description": "写入内容到文件（警告：此操作会完全覆盖原文件。修改已有大文件时请使用 edit_file）",
        "param_descriptions": {"file_path": "文件路径", "content": "内容"},
    },
    "edit_file": {
        "description": "精准替换文件中的文本块 (Search and Replace)。适用于修改已有文件，避免输出整个文件。必须保证 old_str 与文件中的文本完全一致（包括空格和缩进）。如果匹配到多处，将拒绝替换。",
        "param_descriptions": {
            "file_path": "文件绝对或相对路径",
            "old_str": "需要被替换的原文块。建议包含上下文以确保唯一。",
            "new_str": "用来替换 old_str 的新文本块。",
        },
    },
    "grep": {
        "description": "在文件中搜索正则表达式模式 (Search)。返回匹配的文件路径、行号和内容。这是查找代码定义、引用或特定模式的首选工具。",
        "param_descriptions": {
            "pattern": "要搜索的正则表达式 (Python re syntax)",
            "path": "搜索的根目录 (默认为当前目录 .)",
            "glob_pattern": "文件匹配模式 (如 **/*.py, src/*.ts)。默认为 **/*。",
            "case_sensitive": "是否区分大小写 (默认为 False)",
            "max_results": "最大返回结果数 (默认为 50)",
        },
    },
    "list_files": {
        "description": "列出目录中的文件（树形结构）",
        "param_descriptions": {
            "directory": "目录路径",
            "pattern": "文件匹配模式",
            "recursive": "是否递归",
            "max_depth": "最大深度",
        },
    },
    "bash": {
        "description": "执行 Shell 命令。支持 cd 保持目录状态。设置 run_in_background=true 可启动后台进程（如 npm start、uvicorn），用 bash_output 查看输出。",
        "param_descriptions": {
            "command": "要执行的命令",
            "run_in_background": "以后台模式运行（不等待完成，适合启动服务器等长期命令）。默认 False。",
        },
    },
    "bash_output": {
        "description": "读取后台进程的输出，或终止它。用于查看 bash(run_in_background=true) 启动的后台进程。",
        "param_descriptions": {
            "bg_id": "后台进程 ID（bash 返回的 bg_id）",
            "kill": "设为 true 可终止该进程。默认 False（仅读取输出）。",
        },
    },
    "kill_shell": {"description": "重置 Shell 会话状态"},
    "plan_create": {
        "description": "创建一个 DAG 计划（支持并行步骤与阻塞）。",
        "param_descriptions": {
            "title": "计划标题",
            "goal": "计划目标",
            "steps": "步骤数组，每项含 title/depends_on/priority 等字段",
            "expected_version": "可选版本号。已有计划时用于乐观锁校验。",
        },
    },
    "plan_get": {"description": "读取当前会话计划。", "param_descriptions": {"plan_id": "可选计划 ID，用于校验读取对象。"}},
    "plan_update_step": {
        "description": "更新步骤状态或字段（严格状态机 + 乐观锁）。",
        "param_descriptions": {
            "step_id": "步骤 ID",
            "patch": "变更对象（如 status/blocked_reason/priority 等）",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "plan_link_dependency": {
        "description": "更新步骤依赖关系并校验环路。",
        "param_descriptions": {
            "step_id": "步骤 ID",
            "depends_on": "依赖步骤 ID 数组",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "plan_reorder": {
        "description": "重排步骤展示顺序（不改变依赖）。",
        "param_descriptions": {
            "step_orders": "完整的步骤 ID 顺序数组",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "plan_next": {
        "description": "获取下一步建议或并行可执行集合。",
        "param_descriptions": {
            "mode": {"description": "ready|focus|blocked_report", "enum": ["ready", "focus", "blocked_report"]},
            "expected_version": "可选版本号，用于一致性校验",
        },
    },
    "plan_close": {
        "description": "在所有步骤完成后关闭计划。",
        "param_descriptions": {
            "summary": "计划完成总结",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "skill_create": {
        "description": "创建格式正确的 ChainPeer Skill。自动写入 .chainpeer/skills/<name>/SKILL.md 或用户级 ~/.chainpeer/skills/<name>/SKILL.md，并生成稳定的 frontmatter。",
        "param_descriptions": {
            "name": "Skill 名称。只能包含字母、数字、下划线和连字符。",
            "description": "Skill 的简短说明，写入 frontmatter，用于上下文中的 skill index。",
            "body": "SKILL.md 正文指令内容。",
            "triggers": "可选触发短语列表。为空时写入 triggers: []。",
            "scope": {"description": "写入范围：project 写到当前项目，user 写到用户目录。默认 project。", "enum": ["project", "user"]},
            "overwrite": "是否覆盖已存在的 SKILL.md。默认 False。",
        },
    },
    "search_web": {
        "description": "搜索互联网信息。支持多搜索引擎自动切换（Bing/Baidu/DDG），适用于中英文内容查询，中国大陆可用。",
        "param_descriptions": {"query": "搜索关键词（支持中英文）", "max_results": "最大结果数 (默认 5)"},
    },
    "fetch_web_page": {
        "description": "抓取并提取网页主要内容（自动去除导航、广告等干扰，输出Markdown）。通常在 search_web 返回 URL 后使用。",
        "param_descriptions": {"url": "网页 URL"},
    },
}

TOOL_SCHEMAS = build_tool_schemas(TOOLS, _TOOL_SCHEMA_META)

__all__ = ["TOOLS", "TOOL_SCHEMAS"]
