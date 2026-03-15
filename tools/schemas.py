"""工具 Schema 定义"""

TOOL_SCHEMAS = [

    {"type": "function", "function": {
        "name": "read_file",
        "description": "读取文本文件内容",
        "parameters": {
            "type": "object",
            "properties": {"file_path": {"type": "string", "description": "文件路径"}},
            "required": ["file_path"]
        }
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "写入内容到文件",
        "parameters": {
            "type": "object",
            "properties": {"file_path": {"type": "string", "description": "文件路径"}, "content": {"type": "string", "description": "内容"}},
            "required": ["file_path", "content"]
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
]
