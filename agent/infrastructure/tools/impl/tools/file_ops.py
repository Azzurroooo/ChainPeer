"""文件操作工具定义"""
from pathlib import Path
import re

from agent.domain import tool_error, tool_ok
from agent.infrastructure.config.settings import get_workspace_guard

_GREP_SKIP_DIRS = frozenset({
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".tox",
    ".hg", ".svn", "site-packages",
})
_GREP_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

# ── 智能路径检索：常见后缀 & 目录内候选文件 ──
_COMMON_EXTENSIONS = (
    ".py", ".js", ".ts", ".jsx", ".tsx", ".md", ".json",
    ".yaml", ".yml", ".toml", ".cfg", ".ini", ".txt",
    ".html", ".css", ".scss", ".sh", ".bash", ".zsh",
    ".go", ".rs", ".java", ".kt", ".c", ".cpp", ".h",
    ".rb", ".php", ".sql", ".r", ".R", ".lua",
)
_DIR_ENTRY_FILES = (
    "__init__.py", "index.js", "index.ts", "index.tsx",
    "index.py", "main.py", "main.js", "main.ts",
    "mod.rs", "lib.rs", "Cargo.toml", "setup.py",
    "README.md",
)

# ── Session 级 read_file 缓存 ──
_read_cache: dict[str, list[str]] = {}


def _cache_key(path: Path, offset: int, limit: int) -> str:
    """生成缓存键：路径 + 行范围"""
    return f"{path.resolve()}:{offset}:{limit}"


def _smart_resolve(path: Path) -> Path | None:
    """当原始路径不存在或为目录时，尝试智能检索附近变体。
    
    策略优先级：
    1. 原路径为目录 → 查找目录内入口文件（__init__.py 等）
    2. 原路径不存在 → 尝试追加常见后缀（.py, .js 等）
    3. 原路径不存在 → 在父目录中做大小写模糊匹配
    4. 原路径不存在 → 在父目录中做前缀匹配（如 foo 匹配 foo_bar.py）
    
    返回找到的 Path，或 None 表示全部失败。
    """
    # ── 策略1：路径为目录 → 找入口文件 ──
    if path.is_dir():
        for entry_name in _DIR_ENTRY_FILES:
            candidate = path / entry_name
            if candidate.is_file():
                return candidate
        # 目录下没有入口文件，列出目录内所有 .py / .md 文件供参考
        candidates = sorted(
            f for f in path.iterdir()
            if f.is_file() and not f.name.startswith('.')
        )
        if candidates:
            return candidates[0]  # 返回第一个非隐藏文件作为最佳猜测
        return None

    # ── 策略2：追加常见后缀 ──
    if not path.exists():
        # 跳过已有后缀的情况（避免 foo.py → foo.py.py）
        if path.suffix and path.suffix in _COMMON_EXTENSIONS:
            pass  # 已经是常见后缀，不再追加
        else:
            for ext in _COMMON_EXTENSIONS:
                candidate = Path(str(path) + ext)
                if candidate.is_file():
                    return candidate

        # ── 策略3：父目录中大小写模糊匹配 ──
        parent = path.parent
        stem = path.stem.lower()
        suffix = path.suffix.lower()
        if parent.is_dir():
            for sibling in parent.iterdir():
                if not sibling.is_file():
                    continue
                if sibling.stem.lower() == stem and sibling.suffix.lower() == suffix:
                    return sibling

            # ── 策略4：前缀匹配（stem 匹配，要求分隔符边界：foo → foo-bar.py 但不匹配 foo.p）──
            for sibling in sorted(parent.iterdir(), key=lambda s: s.name):
                if not sibling.is_file():
                    continue
                sib_stem_lower = sibling.stem.lower()
                # 只在分隔符边界上匹配：stem 以 target_stem 后紧跟 - 或 _ 开头
                if sib_stem_lower == stem or sib_stem_lower.startswith(stem + "-") or sib_stem_lower.startswith(stem + "_"):
                    return sibling

    return None


def read_file(file_path: str, offset: int = 1, limit: int = 1000) -> str:
    """
    读取文件内容，支持分页和行号显示。
    当路径不存在或指向目录时，自动尝试智能检索附近变体。
    :param file_path: 文件路径
    :param offset: 起始行号 (默认 1)
    :param limit: 读取最大行数 (默认 1000)
    """
    try:
        path = Path(file_path)
        original_path = path
        
        # ── 智能路径检索 ──
        smart_hint = ""
        if not path.is_file():
            resolved = _smart_resolve(path)
            if resolved is not None:
                path = resolved
                smart_hint = f" (智能检索: {original_path} → {path})"
            else:
                # 全部变体都失败，给出详细错误
                if not original_path.exists():
                    # 收集父目录中可能相关的文件名供参考
                    parent = original_path.parent
                    nearby = ""
                    if parent.is_dir():
                        siblings = sorted(
                            f.name for f in parent.iterdir()
                            if f.is_file() and not f.name.startswith('.')
                        )[:10]
                        if siblings:
                            nearby = f"\n父目录中的文件: {', '.join(siblings)}"
                    return tool_error(
                        "read_file",
                        f"文件不存在: {file_path}{nearby}\n提示: 已尝试追加常见后缀和大小写模糊匹配，均未找到匹配文件",
                        "NotFound",
                    )
                else:
                    # 路径存在但不是文件（目录且无入口文件）
                    dir_contents = sorted(
                        f.name for f in original_path.iterdir()
                        if f.is_file() and not f.name.startswith('.')
                    )[:10]
                    contents_hint = ""
                    if dir_contents:
                        contents_hint = f"\n目录中的文件: {', '.join(dir_contents)}"
                    return tool_error(
                        "read_file",
                        f"路径不是文件: {file_path} (这是一个空目录){contents_hint}",
                        "NotAFile",
                    )

        # ── 缓存检查：先查完整文件缓存，再查精确查询缓存 ──
        full_cache_k = _cache_key(path, 1, 999999)
        exact_cache_k = _cache_key(path, offset, limit)

        cached_lines = None
        was_cached = False

        # 优先查完整文件缓存（可服务任意 offset/limit）
        if full_cache_k in _read_cache:
            cached_lines = _read_cache[full_cache_k]
            was_cached = True
        elif exact_cache_k in _read_cache:
            cached_lines = _read_cache[exact_cache_k]
            was_cached = True

        if was_cached and cached_lines is not None:
            total_lines = len(cached_lines)
            end = min(offset - 1 + limit, total_lines)
            result_lines = cached_lines[offset - 1 : end]
            numbered = [f"{i}|{line}" for i, line in zip(range(offset, offset + len(result_lines)), result_lines)]
            content = "\n".join(numbered)
            return tool_ok(
                "read_file",
                content + f"\n\n[缓存命中{smart_hint}] 文件共 {total_lines} 行",
                meta={
                    "file_path": str(path),
                    "offset": offset,
                    "limit": limit,
                    "total_lines": total_lines,
                    "cached": True,
                    "smart_resolved": smart_hint != "",
                },
            )

        # ── 实际读取 ──
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        total_lines = len(raw_lines)

        # 写入完整文件缓存（可被后续任意 offset/limit 查询复用）
        _read_cache[full_cache_k] = raw_lines

        end = min(offset - 1 + limit, total_lines)
        result_lines = raw_lines[offset - 1 : end]
        numbered = [f"{i}|{line}" for i, line in zip(range(offset, offset + len(result_lines)), result_lines)]
        content = "\n".join(numbered)

        return tool_ok(
            "read_file",
            content + f"\n\n[共 {total_lines} 行{smart_hint}]",
            meta={
                "file_path": str(path),
                "offset": offset,
                "limit": limit,
                "total_lines": total_lines,
                "cached": False,
                "smart_resolved": smart_hint != "",
            },
        )
    except Exception as e:
        return tool_error("read_file", f"读取失败: {e}", type(e).__name__)


def write_file(file_path: str, content: str) -> str:
    try:
        guard = get_workspace_guard()
        # Relative paths resolve under the workspace root, not the process
        # cwd — this is what enforces "agent writes land inside the project".
        path = guard.resolve_under_root(file_path)

        violation = guard.check_write(path)
        if violation is not None:
            return tool_error(
                "write_file",
                f"WORKSPACE BOUNDARY VIOLATION: {violation.reason} | Fix: {violation.suggested_fix}",
                "WorkspaceViolation",
                meta={
                    "path": violation.path,
                    "violation_status": violation.status,
                    "workspace_root": str(guard.root),
                    "suggested_fix": violation.suggested_fix,
                },
            )

        is_overwrite = path.exists()
        action = "覆盖" if is_overwrite else "新建"

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        msg = f"成功{action}文件: {path} ({len(content)} 字符)"
        if is_overwrite:
            msg += "\n[警告] 原文件已被完全覆盖。如果这不是你的本意，请使用 edit_file 进行局部修改。"

        return tool_ok("write_file", msg, meta={"file_path": str(path), "action": action, "chars": len(content)})
    except Exception as e:
        return tool_error("write_file", f"写入错误: {e}", type(e).__name__)

def edit_file(file_path: str, old_str: str, new_str: str) -> str:
    """
    精确替换文件中的某一段文本 (Search and Replace)。
    """
    try:
        guard = get_workspace_guard()
        path = guard.resolve_under_root(file_path)

        violation = guard.check_write(path)
        if violation is not None:
            return tool_error(
                "edit_file",
                f"WORKSPACE BOUNDARY VIOLATION: {violation.reason} | Fix: {violation.suggested_fix}",
                "WorkspaceViolation",
                meta={
                    "path": violation.path,
                    "violation_status": violation.status,
                    "workspace_root": str(guard.root),
                    "suggested_fix": violation.suggested_fix,
                },
            )

        if not path.exists():
            return tool_error("edit_file", f"文件不存在: {file_path}", "NotFound")
        if not path.is_file():
            return tool_error("edit_file", f"路径不是文件: {file_path}", "NotAFile")

        if path.stat().st_size > 10 * 1024 * 1024:
            return tool_error("edit_file", "文件过大（>10MB），无法进行全量读取编辑。请考虑使用 Bash 命令或其他方式处理。", "FileTooLarge")

        content = path.read_text(encoding="utf-8")

        if old_str not in content:
            return tool_error("edit_file", "编辑失败：在文件中找不到指定的 old_str (搜索文本)。请确保完全匹配（包括空格、缩进和换行符）。建议先使用 read_file 查看确切的内容。", "OldStrNotFound")

        count = content.count(old_str)
        if count > 1:
            return tool_error(
                "edit_file",
                f"编辑失败：找到 {count} 处匹配的 old_str。为了安全起见，old_str 必须在文件中唯一存在。请在 old_str 中包含更多的上下文行（比如上一行和下一行）以确保唯一性。",
                "OldStrNotUnique",
                meta={"count": count},
            )

        new_content = content.replace(old_str, new_str)
        path.write_text(new_content, encoding="utf-8")
        return tool_ok("edit_file", f"成功：在 {file_path} 中完成了文本替换。", meta={"file_path": str(path)})
    except Exception as e:
        return tool_error("edit_file", f"编辑错误: {e}", type(e).__name__)

def grep(pattern: str, path: str = ".", glob_pattern: str = "**/*", case_sensitive: bool = False, max_results: int = 50) -> str:
    """
    Search for a regex pattern in files.
    """
    try:
        search_path = Path(path).expanduser().resolve()
        if not search_path.exists():
            return tool_error("grep", f"Path does not exist: {path}", "NotFound")

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return tool_error("grep", f"Invalid regex pattern: {e}", "InvalidRegex")

        results: list[dict[str, object]] = []
        match_count = 0

        if search_path.is_file():
            files_to_search = [search_path]
        else:
            files_to_search = search_path.rglob(glob_pattern)

        for file_path in files_to_search:
            if match_count >= max_results:
                break

            if not file_path.is_file():
                continue

            if _GREP_SKIP_DIRS & set(file_path.parts):
                continue

            try:
                if file_path.stat().st_size > _GREP_MAX_FILE_SIZE:
                    continue

                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f):
                        if regex.search(line):
                            try:
                                rel_path = file_path.relative_to(search_path)
                            except ValueError:
                                rel_path = file_path.name

                            line_content = line.strip()
                            if len(line_content) > 200:
                                line_content = line_content[:200] + "..."

                            results.append({"file": str(rel_path), "line": i + 1, "text": line_content})
                            match_count += 1
                            if match_count >= max_results:
                                break
            except Exception:
                continue

        if not results:
            return tool_ok("grep", [], meta={"pattern": pattern, "path": str(search_path), "glob_pattern": glob_pattern, "matches": 0, "truncated": False})

        return tool_ok(
            "grep",
            results,
            meta={
                "pattern": pattern,
                "path": str(search_path),
                "glob_pattern": glob_pattern,
                "matches": len(results),
                "truncated": match_count >= max_results,
            },
        )
    except Exception as e:
        return tool_error("grep", f"Grep error: {e}", type(e).__name__)

def _format_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024: return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

def _build_tree(path: Path, prefix: str = "", depth: int = 0, max_depth: int = 2) -> tuple:
    try:
        items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
    except PermissionError:
        return [f"{prefix}└── [权限拒绝]"], 0, 0
    lines, files, dirs = [], 0, 0
    for i, item in enumerate(items):
        if item.name.startswith('.'): continue
        is_last = i == len(items) - 1
        conn = "└── " if is_last else "├── "
        ext = "    " if is_last else "│   "
        if item.is_dir():
            lines.append(f"{prefix}{conn}📁 {item.name}/")
            if depth < max_depth - 1:
                sub, f, d = _build_tree(item, prefix + ext, depth + 1, max_depth)
                lines.extend(sub)
                dirs += 1 + d
                files += f
            else:
                dirs += 1
        else:
            lines.append(f"{prefix}{conn}📄 {item.name} ({_format_size(item.stat().st_size)})")
            files += 1
    return lines, files, dirs

def list_files(directory: str = ".", pattern: str = "*", recursive: bool = True, max_depth: int = 2) -> str:
    try:
        path = Path(directory).resolve()
        if not path.exists():
            return tool_error("list_files", f"目录不存在: {directory}", "NotFound")
        if not path.is_dir():
            return tool_error("list_files", f"不是目录: {directory}", "NotADirectory")
        if not recursive:
            result = []
            for f in sorted(path.glob(pattern)):
                if f.name.startswith('.'): continue
                if f.is_file(): result.append(f"📄 {f.name} ({_format_size(f.stat().st_size)})")
                else: result.append(f"📁 {f.name}/")
            return tool_ok("list_files", "\n".join(result) or "没有找到文件", meta={"directory": str(path), "recursive": False, "pattern": pattern})
        lines, f, d = _build_tree(path, max_depth=max_depth)
        return tool_ok(
            "list_files",
            "\n".join([f"📁 {path}/"] + lines + ["", f"总计: {d} 个文件夹, {f} 个文件"]),
            meta={"directory": str(path), "recursive": True, "pattern": pattern},
        )
    except Exception as e:
        return tool_error("list_files", f"错误: {e}", type(e).__name__)
