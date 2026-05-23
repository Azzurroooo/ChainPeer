"""Unit tests for read_file smart path resolution + session cache.

These tests exercise the `_smart_resolve` and `read_file` functions
in file_ops.py, using a tmp_path fixture for real filesystem operations.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.infrastructure.tools.impl.tools.file_ops import (
    read_file,
    _smart_resolve,
    _COMMON_EXTENSIONS,
    _DIR_ENTRY_FILES,
    _read_cache,
    _cache_key,
)


def _parse_read_result(raw: str) -> dict:
    """read_file returns JSON string from tool_ok/tool_error. Parse it."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


# ---------------------------------------------------------------------------
# _smart_resolve unit tests
# ---------------------------------------------------------------------------


class TestSmartResolveDirectory:
    """Strategy 1: path is a directory → find entry file."""

    def test_dir_with_init_py(self, tmp_path: Path):
        pkg_dir = tmp_path / "mypkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("# init\n")
        result = _smart_resolve(pkg_dir)
        assert result is not None
        assert result.name == "__init__.py"

    def test_dir_with_index_js(self, tmp_path: Path):
        dir_ = tmp_path / "components"
        dir_.mkdir()
        (dir_ / "index.js").write_text("// entry\n")
        result = _smart_resolve(dir_)
        assert result is not None
        assert result.name == "index.js"

    def test_dir_with_no_entry_file_falls_to_first_regular(self, tmp_path: Path):
        dir_ = tmp_path / "notes"
        dir_.mkdir()
        (dir_ / "readme.txt").write_text("hello")
        (dir_ / "data.csv").write_text("a,b")
        result = _smart_resolve(dir_)
        assert result is not None
        # Sorted order → data.csv comes before readme.txt
        assert result.name == "data.csv"

    def test_empty_dir_returns_none(self, tmp_path: Path):
        dir_ = tmp_path / "emptyish"
        dir_.mkdir()
        (dir_ / ".gitkeep").write_text("")
        result = _smart_resolve(dir_)
        assert result is None


class TestSmartResolveExtensionAppend:
    """Strategy 2: append common extensions."""

    def test_missing_py_file_with_py_ext(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("print('hi')\n")
        result = _smart_resolve(tmp_path / "app")
        assert result is not None
        assert result.name == "app.py"

    def test_missing_js_file(self, tmp_path: Path):
        (tmp_path / "utils.js").write_text("// utils\n")
        result = _smart_resolve(tmp_path / "utils")
        assert result is not None
        assert result.name == "utils.js"

    def test_existing_common_suffix_no_double_append(self, tmp_path: Path):
        """If the path already has a common suffix (.py), don't double-append.
        foo.py doesn't exist → should not resolve to foo.py.py."""
        (tmp_path / "foo.py.py").write_text("bad\n")
        result = _smart_resolve(tmp_path / "foo.py")
        # Should NOT resolve to foo.py.py (since foo.py already has .py suffix)
        assert result is None or result.name != "foo.py.py"

    def test_no_extension_match_returns_none(self, tmp_path: Path):
        result = _smart_resolve(tmp_path / "does_not_exist_anywhere")
        assert result is None


class TestSmartResolveCaseFuzzy:
    """Strategy 3: case-insensitive fuzzy match in parent dir."""

    def test_case_insensitive_match(self, tmp_path: Path):
        (tmp_path / "MyModule.py").write_text("code\n")
        result = _smart_resolve(tmp_path / "mymodule.py")
        assert result is not None
        assert result.name == "MyModule.py"

    def test_case_match_with_different_suffix(self, tmp_path: Path):
        (tmp_path / "Foo.JS").write_text("// JS\n")
        result = _smart_resolve(tmp_path / "foo.js")
        assert result is not None
        assert result.name == "Foo.JS"


class TestSmartResolvePrefixMatch:
    """Strategy 4: prefix match (stem starts with requested stem)."""

    def test_prefix_match(self, tmp_path: Path):
        (tmp_path / "config_loader.py").write_text("load\n")
        result = _smart_resolve(tmp_path / "config")
        assert result is not None
        assert result.name == "config_loader.py"


# ---------------------------------------------------------------------------
# read_file integration tests
# ---------------------------------------------------------------------------


class TestReadFileSmartResolve:
    """read_file automatically uses smart resolution."""

    def setup_method(self):
        _read_cache.clear()

    def test_read_dir_resolves_to_init(self, tmp_path: Path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# package init\n")
        raw = read_file(str(pkg))
        parsed = _parse_read_result(raw)
        assert parsed["ok"] is True
        assert "package init" in parsed["data"]
        assert parsed["meta"]["smart_resolved"] is True

    def test_read_missing_with_ext_append(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("print('hello')\n")
        raw = read_file(str(tmp_path / "app"))
        parsed = _parse_read_result(raw)
        assert parsed["ok"] is True
        assert "hello" in parsed["data"]
        assert parsed["meta"]["smart_resolved"] is True

    def test_read_missing_no_variants(self, tmp_path: Path):
        (tmp_path / "other.py").write_text("x\n")
        (tmp_path / "main.js").write_text("y\n")
        raw = read_file(str(tmp_path / "nonexistent.py"))
        parsed = _parse_read_result(raw)
        assert parsed["ok"] is False
        # Error should mention nearby files or NotFound
        assert "NotFound" in parsed.get("error_type", "") or "父目录" in parsed.get("error", "")


class TestReadFileCache:
    """Session-level cache for read_file."""

    def setup_method(self):
        _read_cache.clear()

    def test_cache_hit_on_second_read(self, tmp_path: Path):
        f = tmp_path / "cached.txt"
        f.write_text("line1\nline2\nline3\n")

        r1 = _parse_read_result(read_file(str(f)))
        assert r1["meta"]["cached"] is False

        r2 = _parse_read_result(read_file(str(f)))
        assert r2["meta"]["cached"] is True

        # Content data should be similar
        assert "line1" in r1["data"]
        assert "line1" in r2["data"]

    def test_cache_different_offset(self, tmp_path: Path):
        f = tmp_path / "long.txt"
        lines = [f"line {i}" for i in range(1, 101)]
        f.write_text("\n".join(lines) + "\n")

        r1 = _parse_read_result(read_file(str(f), offset=1, limit=50))
        assert r1["meta"]["cached"] is False

        r2 = _parse_read_result(read_file(str(f), offset=51, limit=50))
        assert r2["meta"]["cached"] is True
        assert "line 51" in r2["data"]

    def test_cache_clear_between_tests(self, tmp_path: Path):
        f = tmp_path / "fresh.txt"
        f.write_text("fresh content\n")
        r = _parse_read_result(read_file(str(f)))
        assert r["meta"]["cached"] is False


class TestReadFileBasic:
    """Basic read_file functionality (unchanged behavior)."""

    def setup_method(self):
        _read_cache.clear()

    def test_read_existing_file(self, tmp_path: Path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')\n")
        raw = read_file(str(f))
        parsed = _parse_read_result(raw)
        assert parsed["ok"] is True
        assert "print('hello')" in parsed["data"]

    def test_read_with_offset(self, tmp_path: Path):
        f = tmp_path / "multi.txt"
        f.write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n")
        raw = read_file(str(f), offset=5, limit=3)
        parsed = _parse_read_result(raw)
        assert parsed["ok"] is True
        assert "line5" in parsed["data"]
        assert "line7" in parsed["data"]
        assert "line4" not in parsed["data"]

    def test_read_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        raw = read_file(str(f))
        parsed = _parse_read_result(raw)
        assert parsed["ok"] is True

    def test_path_is_dir_with_no_files(self, tmp_path: Path):
        d = tmp_path / "emptydir"
        d.mkdir()
        raw = read_file(str(d))
        parsed = _parse_read_result(raw)
        assert parsed["ok"] is False
        assert "NotAFile" in parsed.get("error_type", "") or "不是文件" in parsed.get("error", "")