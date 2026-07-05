from __future__ import annotations

from pathlib import Path

from synology_site.upload_filter import build_ignore_matcher, load_dockerignore_patterns


def test_load_dockerignore_patterns_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    dockerignore = tmp_path / ".dockerignore"
    dockerignore.write_text("node_modules\n# a comment\n\n*.md\n")

    assert load_dockerignore_patterns(dockerignore) == ["node_modules", "*.md"]


def test_load_dockerignore_patterns_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_dockerignore_patterns(tmp_path / "missing") == []


def test_ignore_matcher_matches_bare_name_at_any_depth() -> None:
    is_ignored = build_ignore_matcher(["node_modules"])

    assert is_ignored(Path("node_modules/foo.js"))
    assert is_ignored(Path("apps/web/node_modules/foo.js"))
    assert not is_ignored(Path("apps/web/src/index.ts"))


def test_ignore_matcher_strips_leading_doublestar_prefix() -> None:
    is_ignored = build_ignore_matcher(["**/dist"])

    assert is_ignored(Path("apps/web/dist/bundle.js"))
    assert is_ignored(Path("dist/bundle.js"))


def test_ignore_matcher_matches_glob_names() -> None:
    is_ignored = build_ignore_matcher(["*.md"])

    assert is_ignored(Path("README.md"))
    assert is_ignored(Path("docs/CHANGELOG.md"))
    assert not is_ignored(Path("app.ts"))


def test_ignore_matcher_matches_exact_filename() -> None:
    is_ignored = build_ignore_matcher(["jira_import.csv"])

    assert is_ignored(Path("jira_import.csv"))
    assert not is_ignored(Path("other.csv"))
