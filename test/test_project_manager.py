"""Unit tests for the project-level workspace partition manager.

These tests exercise the project_manager module: slugify, extract_project_name,
fuzzy match scoring, and find_or_create_project_dir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.domain.project_manager import (
    _slugify,
    extract_project_name,
    _fuzzy_match_score,
    _levenshtein,
    find_or_create_project_dir,
)


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_ascii_text(self):
        assert _slugify("Hello World") == "hello-world"

    def test_hyphens_preserved(self):
        assert _slugify("my-cool-project") == "my-cool-project"

    def test_multiple_spaces_collapsed(self):
        assert _slugify("foo   bar   baz") == "foo-bar-baz"

    def test_special_chars_removed(self):
        assert _slugify("Hello! @World# 2024") == "hello-world-2024"

    def test_empty_input_fallback(self):
        assert _slugify("") == "unnamed-project"

    def test_unicode_normalization(self):
        # NFKD normalization: ﬁ → fi
        result = _slugify("ﬁle-manager")
        assert result == "file-manager"

    def test_leading_trailing_hyphens_removed(self):
        assert _slugify("---hello---") == "hello"

    def test_only_special_chars(self):
        assert _slugify("@@@") == "unnamed-project"


# ---------------------------------------------------------------------------
# extract_project_name
# ---------------------------------------------------------------------------


class TestExtractProjectName:
    def test_md_filename(self):
        assert extract_project_name("chainpeer.md describes a project") == "chainpeer"

    def test_md_filename_with_path(self):
        assert extract_project_name("docs/quant_alpha.md task") == "quant-alpha" or \
               extract_project_name("docs/quant_alpha.md task") == "quant_alpha"

    def test_path_like(self):
        result = extract_project_name("优化 my_app/ 中的性能")
        assert "my_app" in result

    def test_empty_string(self):
        assert extract_project_name("") == "default"

    def test_short_description(self):
        result = extract_project_name("fix the bug")
        assert result == "fix the bug"

    def test_quoted_name(self):
        result = extract_project_name("「chainpeer」项目优化")
        assert result == "chainpeer"


# ---------------------------------------------------------------------------
# _fuzzy_match_score
# ---------------------------------------------------------------------------


class TestFuzzyMatchScore:
    def test_exact_match(self):
        assert _fuzzy_match_score("foo-bar", "foo-bar") == 1.0

    def test_no_match(self):
        assert _fuzzy_match_score("abc", "xyz") < 0.1

    def test_keyword_overlap(self):
        score = _fuzzy_match_score("chain-peer", "chain-peer-v2")
        assert score >= 0.7  # "chain" and "peer" overlap

    def test_partial_keyword_overlap(self):
        score = _fuzzy_match_score("chain", "chain-peer")
        assert score >= 0.7  # "chain" overlaps

    def test_levenshtein_proximity(self):
        score = _fuzzy_match_score("chainpeer", "chainpeerv2")
        # Levenshtein distance = 2, max_len = 11 → similarity ≈ 0.82 → scaled ≈ 0.49
        # But keyword match may trigger first since "chainpeer" is one token
        assert score > 0.0

    def test_empty_strings(self):
        assert _fuzzy_match_score("", "") == 1.0


# ---------------------------------------------------------------------------
# _levenshtein
# ---------------------------------------------------------------------------


class TestLevenshtein:
    def test_same_string(self):
        assert _levenshtein("abc", "abc") == 0

    def test_one_deletion(self):
        assert _levenshtein("abcd", "abc") == 1

    def test_one_insertion(self):
        assert _levenshtein("abc", "abcd") == 1

    def test_one_substitution(self):
        assert _levenshtein("abc", "axc") == 1

    def test_empty_strings(self):
        assert _levenshtein("", "") == 0
        assert _levenshtein("abc", "") == 3
        assert _levenshtein("", "abc") == 3


# ---------------------------------------------------------------------------
# find_or_create_project_dir
# ---------------------------------------------------------------------------


class TestFindOrCreateProjectDir:
    def test_new_project_creates_dir(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "my new project")
        assert result.is_dir()
        assert result.parent == ws_root

    def test_exact_match_reuses_dir(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        existing = ws_root / "my-new-project"
        existing.mkdir()

        result = find_or_create_project_dir(ws_root, "my new project")
        assert result == existing.resolve()

    def test_fuzzy_match_reuses_dir(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        existing = ws_root / "chain-peer-v2"
        existing.mkdir()

        # "chain peer v2" → slug "chain-peer-v2", keywords overlap with existing
        result = find_or_create_project_dir(ws_root, "chain peer v2")
        assert result == existing.resolve()

    def test_no_match_creates_new(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        existing = ws_root / "totally-different"
        existing.mkdir()

        result = find_or_create_project_dir(ws_root, "brand new project")
        assert result != existing.resolve()
        assert result.is_dir()

    def test_skips_hidden_dirs(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        (ws_root / ".hidden").mkdir()

        result = find_or_create_project_dir(ws_root, "hidden project")
        # Should not reuse .hidden
        assert not result.name.startswith(".")

    def test_md_file_name(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "chainpeer.md project description")
        assert result.name == "chainpeer"

    def test_workspace_root_auto_created(self, tmp_path: Path):
        ws_root = tmp_path / "nonexistent_workspace"
        result = find_or_create_project_dir(ws_root, "test project")
        assert ws_root.is_dir()
        assert result.is_dir()