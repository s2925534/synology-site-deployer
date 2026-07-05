from __future__ import annotations

from synology_site.supabase.env_overrides import apply_env_overrides


def test_apply_env_overrides_replaces_matching_keys() -> None:
    original = "\n".join(
        [
            "# a comment",
            "POSTGRES_PASSWORD=this_password_is_insecure_and_should_be_updated",
            "",
            "STUDIO_DEFAULT_ORGANIZATION=Default Organization",
        ]
    )

    result = apply_env_overrides(original, {"POSTGRES_PASSWORD": "generated-secret"})

    lines = result.splitlines()
    assert "POSTGRES_PASSWORD=generated-secret" in lines
    assert "# a comment" in lines
    assert "STUDIO_DEFAULT_ORGANIZATION=Default Organization" in lines
    assert result.endswith("\n")


def test_apply_env_overrides_appends_keys_not_present() -> None:
    result = apply_env_overrides("EXISTING=1", {"NEW_KEY": "value"})

    assert "EXISTING=1" in result.splitlines()
    assert "NEW_KEY=value" in result.splitlines()


def test_apply_env_overrides_ignores_commented_lines() -> None:
    original = "# POSTGRES_PASSWORD=example-only-a-comment"

    result = apply_env_overrides(original, {"POSTGRES_PASSWORD": "generated-secret"})

    assert "# POSTGRES_PASSWORD=example-only-a-comment" in result.splitlines()
    assert "POSTGRES_PASSWORD=generated-secret" in result.splitlines()
