"""工具 Schema 定义"""

TOOL_SCHEMAS = [

    {"type": "function", "function": {
        "name": "read_file",
        "description": "读取文本文件内容，支持行号和分页读取。Agent应通过此工具查看代码上下文。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件绝对或相对路径"},
                "offset": {"type": "integer", "description": "起始行号（默认 1）", "default": 1},
                "limit": {"type": "integer", "description": "最多读取的行数（默认 1000 行，避免大文件超出上下文）", "default": 1000}
            },
            "required": ["file_path"]
        }
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "写入内容到文件（警告：此操作会完全覆盖原文件。修改已有大文件时请使用 edit_file）",
        "parameters": {
            "type": "object",
            "properties": {"file_path": {"type": "string", "description": "文件路径"}, "content": {"type": "string", "description": "内容"}},
            "required": ["file_path", "content"]
        }
    }},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "精准替换文件中的文本块 (Search and Replace)。适用于修改已有文件，避免输出整个文件。必须保证 old_str 与文件中的文本完全一致（包括空格和缩进）。如果匹配到多处，将拒绝替换。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "文件绝对或相对路径"},
                "old_str": {"type": "string", "description": "需要被替换的原文块。建议包含上下文（比如目标行的上一行和下一行），以确保在文件中是唯一存在的。"},
                "new_str": {"type": "string", "description": "用来替换 old_str 的新文本块。"}
            },
            "required": ["file_path", "old_str", "new_str"]
        }
    }},
    {"type": "function", "function": {
        "name": "grep",
        "description": "在文件中搜索正则表达式模式 (Search)。返回匹配的文件路径、行号和内容。这是查找代码定义、引用或特定模式的首选工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "要搜索的正则表达式 (Python re syntax)"},
                "path": {"type": "string", "description": "搜索的根目录 (默认为当前目录 .)", "default": "."},
                "glob_pattern": {"type": "string", "description": "文件匹配模式 (如 **/*.py, src/*.ts)。默认为 **/* (递归搜索所有文件)。", "default": "**/*"},
                "case_sensitive": {"type": "boolean", "description": "是否区分大小写 (默认为 False)", "default": False},
                "max_results": {"type": "integer", "description": "最大返回结果数 (默认为 50)", "default": 50}
            },
            "required": ["pattern"]
        }
    }},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "列出目录中的文件（树形结构）",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "default": ".", "description": "目录路径"},
                "pattern": {"type": "string", "default": "*", "description": "文件匹配模式"},
                "recursive": {"type": "boolean", "default": True, "description": "是否递归"},
                "max_depth": {"type": "integer", "default": 2, "description": "最大深度"}
            },
            "required": []
        }
    }},
    {"type": "function", "function": {
        "name": "bash",
        "description": "执行 Shell 命令 (支持 cd 保持目录状态)",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令 (如: ls -la, git status)"}
            },
            "required": ["command"]
        }
    }},
    {"type": "function", "function": {
        "name": "kill_shell",
        "description": "重置 Shell 会话状态",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }},
    {"type": "function", "function": {
        "name": "search_web",
        "description": "搜索互联网上的信息。当不知道具体问题的答案、需要最新信息或查找外部文档时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "description": "最大结果数 (默认 5)", "default": 5}
            },
            "required": ["query"]
        }
    }},
    {"type": "function", "function": {
        "name": "fetch_web_page",
        "description": "抓取并读取网页内容 (转换为 Markdown)。通常在 search_web 返回 URL 后使用，以获取详细信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "网页 URL"}
            },
            "required": ["url"]
        }
    }},
]
