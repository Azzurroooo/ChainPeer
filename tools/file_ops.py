"""文件操作工具定义"""
from pathlib import Path
import re

def read_file(file_path: str, offset: int = 1, limit: int = 1000) -> str:
    """
    读取文件内容，支持分页和行号显示。
    :param file_path: 文件路径
    :param offset: 起始行号 (默认 1)
    :param limit: 读取最大行数 (默认 1000)
    """
    try:
        path = Path(file_path)
        if not path.exists(): return f"文件不存在: {file_path}"
        if not path.is_file(): return f"路径不是文件: {file_path}"
        if path.stat().st_size > 10 * 1024 * 1024: return "文件过大（>10MB），请使用更精确的搜索或限制读取范围。"
        
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        total_lines = len(lines)
        start_idx = max(0, offset - 1)
        end_idx = min(total_lines, start_idx + limit)
        
        if start_idx >= total_lines:
            return f"起始行 {offset} 超出文件总行数 ({total_lines} 行)。"
            
        # 附带行号输出
        output = [f"Showing lines {start_idx + 1} to {end_idx} of {total_lines}:"]
        for i in range(start_idx, end_idx):
            # 格式化行号，占位 4 个字符以保持对齐
            output.append(f"{i + 1:4d} | {lines[i].rstrip('\n')}")
            
        return "\n".join(output)
    except Exception as e:
        return f"读取错误: {e}"

def write_file(file_path: str, content: str) -> str:
    try:
        path = Path(file_path).expanduser().resolve()
        
        # 检查是否为覆盖写入
        is_overwrite = path.exists()
        action = "覆盖" if is_overwrite else "新建"
        
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        
        # 返回更明确的操作反馈，如果是覆盖，提醒 Agent 注意
        msg = f"成功{action}文件: {path} ({len(content)} 字符)"
        if is_overwrite:
            msg += "\n[警告] 原文件已被完全覆盖。如果这不是你的本意，请使用 edit_file 进行局部修改。"
            
        return msg
    except Exception as e:
        return f"写入错误: {e}"

def edit_file(file_path: str, old_str: str, new_str: str) -> str:
    """
    精确替换文件中的某一段文本 (Search and Replace)。
    """
    try:
        path = Path(file_path).expanduser().resolve()
        if not path.exists(): return f"文件不存在: {file_path}"
        if not path.is_file(): return f"路径不是文件: {file_path}"
        
        # 安全检查：防止读取超大文件导致内存爆炸
        if path.stat().st_size > 10 * 1024 * 1024: 
            return "文件过大（>10MB），无法进行全量读取编辑。请考虑使用 Bash 命令或其他方式处理。"

        content = path.read_text(encoding="utf-8")
        
        if old_str not in content:
            return "编辑失败：在文件中找不到指定的 old_str (搜索文本)。请确保完全匹配（包括空格、缩进和换行符）。建议先使用 read_file 查看确切的内容。"
            
        # 统计匹配次数，为了安全，强制要求 old_str 在文件中唯一
        count = content.count(old_str)
        if count > 1:
            return f"编辑失败：找到 {count} 处匹配的 old_str。为了安全起见，old_str 必须在文件中唯一存在。请在 old_str 中包含更多的上下文行（比如上一行和下一行）以确保唯一性。"
            
        new_content = content.replace(old_str, new_str)
        path.write_text(new_content, encoding="utf-8")
        return f"成功：在 {file_path} 中完成了文本替换。"
    except Exception as e:
        return f"编辑错误: {e}"

def grep(pattern: str, path: str = ".", glob_pattern: str = "**/*", case_sensitive: bool = False, max_results: int = 50) -> str:
    """
    Search for a regex pattern in files.
    """
    try:
        search_path = Path(path).expanduser().resolve()
        if not search_path.exists():
            return f"Path does not exist: {path}"
        
        # Compile regex
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Invalid regex pattern: {e}"

        results = []
        match_count = 0
        
        # Determine files to search
        if search_path.is_file():
            files_to_search = [search_path]
        else:
            # Use rglob for recursive search by default with glob_pattern
            files_to_search = search_path.rglob(glob_pattern)

        for file_path in files_to_search:
            if match_count >= max_results:
                results.append(f"... (Truncated after {max_results} matches)")
                break
                
            if not file_path.is_file():
                continue
            
            # Skip .git and other common hidden directories to improve performance/relevance
            if ".git" in file_path.parts:
                continue

            try:
                # Skip large files (>1MB) to keep search fast
                if file_path.stat().st_size > 1 * 1024 * 1024:
                    continue
                
                # Read line by line to avoid loading huge files into memory
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f):
                        if regex.search(line):
                            try:
                                rel_path = file_path.relative_to(search_path)
                            except ValueError:
                                rel_path = file_path.name
                            
                            # Truncate very long lines
                            line_content = line.strip()
                            if len(line_content) > 200:
                                line_content = line_content[:200] + "..."

                            results.append(f"{rel_path}:{i + 1}: {line_content}")
                            match_count += 1
                            if match_count >= max_results:
                                break
            except Exception:
                continue # Skip unreadable files
                
        if not results:
            return f"No matches found for pattern: '{pattern}' in {path} with glob '{glob_pattern}'"
            
        return "\n".join(results)
    except Exception as e:
        return f"Grep error: {e}"

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
