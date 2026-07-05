from __future__ import annotations

import fnmatch
from pathlib import Path


def load_dockerignore_patterns(dockerignore_path: Path) -> list[str]:
    if not dockerignore_path.is_file():
        return []
    patterns = []
    for line in dockerignore_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return patterns


def build_ignore_matcher(patterns: list[str]):
    """Builds a relative-path predicate from .dockerignore-style patterns.

    A pattern with no "/" (after stripping an optional "**/" prefix, which
    is the common "match at any depth" idiom) is treated as a name pattern
    and matched against every path component. A pattern that still has a
    "/" after that is matched against the whole relative posix path. This
    covers the common real-world case (bare directory/file names) without
    implementing full gitignore-style precedence/negation semantics.
    """
    name_patterns: list[str] = []
    path_patterns: list[str] = []
    for raw in patterns:
        pat = raw.strip().rstrip("/")
        if not pat:
            continue
        if pat.startswith("**/"):
            pat = pat[3:]
        if "/" in pat:
            path_patterns.append(pat)
        else:
            name_patterns.append(pat)

    def is_ignored(relative_path: Path) -> bool:
        if any(fnmatch.fnmatch(part, pat) for part in relative_path.parts for pat in name_patterns):
            return True
        posix = relative_path.as_posix()
        return any(fnmatch.fnmatch(posix, pat) for pat in path_patterns)

    return is_ignored
