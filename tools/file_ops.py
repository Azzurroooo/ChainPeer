"""文件操作工具定义"""
from pathlib import Path

def read_file(file_path: str) -> str:
    try:
        path = Path(file_path)
        if not path.exists(): return f"文件不存在: {file_path}"
        if not path.is_file(): return f"路径不是文件: {file_path}"
        if path.stat().st_size > 10 * 1024 * 1024: return "文件过大（>10MB）"
        return path.read_text(encoding="utf-8")[:10000]
    except Exception as e:
        return f"读取错误: {e}"

def write_file(file_path: str, content: str) -> str:
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"成功写入: {file_path} ({len(content)} 字符)"
    except Exception as e:
        return f"写入错误: {e}"

def _format_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024: return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

def _build_tree(path: Path, prefix: str = "") -> tuple:
    try: items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
    except PermissionError: return [f"{prefix}└── [权限拒绝]"], 0, 0
    lines, files, dirs = [], 0, 0
    for i, item in enumerate(items):
        if item.name.startswith('.'): continue
        is_last = i == len(items) - 1
        conn = "└── " if is_last else "├── "
        ext = "    " if is_last else "│   "
        if item.is_dir():
            lines.append(f"{prefix}{conn}📁 {item.name}/")
            sub, f, d = _build_tree(item, prefix + ext)
            lines.extend(sub)
            dirs += 1 + d
            files += f
        else:
            lines.append(f"{prefix}{conn}📄 {item.name} ({_format_size(item.stat().st_size)})")
            files += 1
    return lines, files, dirs

def list_files(directory: str = ".", pattern: str = "*", recursive: bool = True, max_depth: int = 2) -> str:
    try:
        path = Path(directory).resolve()
        if not path.exists(): return f"目录不存在: {directory}"
        if not path.is_dir(): return f"不是目录: {directory}"
        if not recursive:
            result = []
            for f in sorted(path.glob(pattern)):
                if f.name.startswith('.'): continue
                if f.is_file(): result.append(f"📄 {f.name} ({_format_size(f.stat().st_size)})")
                else: result.append(f"📁 {f.name}/")
            return "\n".join(result) or "没有找到文件"
        lines, f, d = _build_tree(path)
        return "\n".join([f"📁 {path}/"] + lines + ["", f"总计: {d} 个文件夹, {f} 个文件"])
    except Exception as e:
        return f"错误: {e}"
