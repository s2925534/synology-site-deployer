from __future__ import annotations


def apply_env_overrides(env_text: str, overrides: dict[str, str]) -> str:
    """Rewrites KEY=... lines in env_text with values from overrides.

    Keys present in overrides but not found in env_text are appended.
    Preserves comments, blank lines, and every other key untouched.
    """
    remaining = dict(overrides)
    result: list[str] = []
    for line in env_text.splitlines():
        stripped = line.strip()
        is_assignment = "=" in stripped and not stripped.startswith("#")
        key = stripped.split("=", 1)[0] if is_assignment else None
        if key is not None and key in remaining:
            result.append(f"{key}={remaining.pop(key)}")
        else:
            result.append(line)
    for key, value in remaining.items():
        result.append(f"{key}={value}")
    return "\n".join(result) + "\n"
