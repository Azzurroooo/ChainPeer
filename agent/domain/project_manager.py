"""项目级 Workspace 分区管理器。

负责：
1. 从用户任务描述 / MD 文件 / 项目名提取项目标识
2. 在 workspace_root 下按项目建子目录
3. 新任务启动时自动模糊匹配已有项目目录（keyword + levenshtein）
   找到则复用该目录而非新建

设计原则：
- 每个项目在 workspace_root 下有一个独立子目录
- 目录名 = project_slug（slugified from project name / md title）
- 支持模糊回溯已有项目（keyword match > levenshtein proximity）
"""

import re
import unicodedata
from pathlib import Path


def _slugify(text: str) -> str:
    """将自然语言文本转为 URL-safe slug（用于目录名）。

    >>> _slugify("我的量化策略项目")
    'wo-de-liang-hua-ce-lve-xiang-mu'
    >>> _slugify("ChainPeer - Decentralized Consensus")
    'chainpeer-decentralized-consensus'
    """
    # Normalize unicode → ASCII equivalents where possible
    text = unicodedata.normalize("NFKD", text)
    # Remove non-ASCII, non-alphanumeric (keep spaces, hyphens, underscores)
    text = re.sub(r"[^\w\s\-]", "", text)
    # Replace spaces/underscores with hyphens
    text = re.sub(r"[\s_]+", "-", text)
    # Lowercase
    text = text.lower().strip("-")
    # Collapse multiple hyphens
    text = re.sub(r"-{2,}", "-", text)
    # Transliterate CJK characters — use pinyin-like romanization or just remove
    # For simplicity, remove non-ascii chars remaining after normalization
    text = re.sub(r"[^\x00-\x7F]", "", text)
    # Remove leading/trailing hyphens
    text = text.strip("-")
    # Fallback if empty
    if not text:
        text = "unnamed-project"
    return text


def extract_project_name(task_description: str) -> str:
    """从任务描述中提取项目名称。

    策略：
    1. 如果任务描述中包含 markdown 文件名（*.md），提取文件名作为项目名
    2. 否则提取第一句/第一个短语作为项目名
    3. 如果描述太短或为空，返回 "default"

    >>> extract_project_name("优化 my_app/ 中的性能问题")
    '优化 my_app 中的性能问题'
    >>> extract_project_name("chainpeer.md 描述的项目")
    'chainpeer'
    """
    if not task_description or not task_description.strip():
        return "default"

    # 尝试提取 .md 文件名
    md_match = re.search(r"([\w\-]+)\.md", task_description)
    if md_match:
        return md_match.group(1)

    # 尝试提取引号/书名号中的项目名
    quoted_match = re.search(r"[\"「《『]([\w\-]+)[\"」》』]", task_description)
    if quoted_match:
        return quoted_match.group(1)

    # 尝试提取路径名（如 my_app/）
    path_match = re.search(r"([\w\-]+)/", task_description)
    if path_match:
        return path_match.group(1)

    # 取前 30 个字符作为项目名（去掉标点）
    first_phrase = re.sub(r"[^\w\s\-]", "", task_description.strip())[:30].strip()
    if first_phrase:
        return first_phrase

    return "default"


def _fuzzy_match_score(slug: str, existing_slug: str) -> float:
    """计算两个 slug 之间的模糊匹配分数 (0~1)。

    策略（优先级从高到低）：
    1. 完全匹配 → 1.0
    2. keyword match（slug 包含 existing_slug 的关键词）→ 0.7~0.9
    3. Levenshtein proximity → 0~0.6
    """
    if slug == existing_slug:
        return 1.0

    # keyword match: 如果 slug 包含 existing_slug 中的主要词段
    slug_parts = set(slug.split("-"))
    existing_parts = set(existing_slug.split("-"))
    overlap = slug_parts & existing_parts
    if overlap:
        ratio = len(overlap) / max(len(slug_parts), len(existing_parts))
        return 0.7 + 0.2 * ratio  # 0.7 ~ 0.9

    # Levenshtein distance (simplified: only for short strings)
    if len(slug) < 30 and len(existing_slug) < 30:
        dist = _levenshtein(slug, existing_slug)
        max_len = max(len(slug), len(existing_slug))
        if max_len == 0:
            return 0.0
        similarity = 1.0 - dist / max_len
        return similarity * 0.6  # scale to 0 ~ 0.6

    return 0.0


def _levenshtein(a: str, b: str) -> int:
    """计算两个字符串之间的 Levenshtein 编辑距离。"""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev_row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr_row = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr_row.append(min(
                prev_row[j + 1] + 1,  # deletion
                curr_row[j] + 1,      # insertion
                prev_row[j] + cost,   # substitution
            ))
        prev_row = curr_row
    return prev_row[-1]


def find_or_create_project_dir(
    workspace_root: Path,
    task_description: str,
    threshold: float = 0.6,
) -> Path:
    """在 workspace_root 下查找或创建项目子目录。

    流程：
    1. 从 task_description 提取项目名 → slugify → project_slug
    2. 检查 workspace_root/project_slug 是否存在 → 直接返回
    3. 模糊匹配已有项目目录（threshold ≥ 0.6 视为匹配）
    4. 无匹配则创建新目录 workspace_root/project_slug

    :param workspace_root: 工作区根目录（如 ~/quanora-projects）
    :param task_description: 用户任务描述
    :param threshold: 模糊匹配阈值（0~1），默认 0.6
    :return: 项目子目录的绝对路径
    """
    project_name = extract_project_name(task_description)
    project_slug = _slugify(project_name)

    # 确保 workspace_root 存在
    workspace_root.mkdir(parents=True, exist_ok=True)

    # 1. 精确匹配
    exact_dir = workspace_root / project_slug
    if exact_dir.is_dir():
        return exact_dir.resolve()

    # 2. 模糊匹配已有项目目录
    best_match: Path | None = None
    best_score: float = 0.0

    for child in workspace_root.iterdir():
        if not child.is_dir():
            continue
        # 跳过隐藏目录
        if child.name.startswith("."):
            continue
        score = _fuzzy_match_score(project_slug, child.name)
        if score > best_score:
            best_score = score
            best_match = child

    if best_match is not None and best_score >= threshold:
        return best_match.resolve()

    # 3. 无匹配 → 创建新项目目录
    exact_dir.mkdir(parents=True, exist_ok=True)
    return exact_dir.resolve()