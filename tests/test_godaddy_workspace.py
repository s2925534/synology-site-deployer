from __future__ import annotations

from pathlib import Path

from synology_site.godaddy.workspace import (
    GoDaddyAccount,
    discover_godaddy_accounts,
    resolve_godaddy_account,
)


def default_account() -> GoDaddyAccount:
    return GoDaddyAccount(name="default", access_token=None, api_key=None, api_secret=None)


def test_discover_godaddy_accounts_scans_secrets_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "veloso-dev"
    workspace.mkdir()
    (workspace / "godaddy.env").write_text(
        "GD_ACCESS_TOKEN=token123\nGD_ENVIRONMENT=ote\n", encoding="utf-8"
    )

    accounts = discover_godaddy_accounts(tmp_path)

    assert len(accounts) == 1
    assert accounts[0].name == "veloso-dev"
    assert accounts[0].access_token == "token123"
    assert accounts[0].environment == "ote"
    assert accounts[0].ready is True


def test_discover_godaddy_accounts_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    assert discover_godaddy_accounts(tmp_path / "does-not-exist") == ()


def test_godaddy_account_ready_with_sso_key_pair() -> None:
    account = GoDaddyAccount(name="x", access_token=None, api_key="key", api_secret="secret")
    assert account.ready is True


def test_godaddy_account_not_ready_with_only_api_key() -> None:
    account = GoDaddyAccount(name="x", access_token=None, api_key="key", api_secret=None)
    assert account.ready is False


def test_godaddy_account_base_url_defaults_to_production() -> None:
    account = GoDaddyAccount(name="x", access_token="t", api_key=None, api_secret=None)
    assert account.base_url == "https://api.godaddy.com"


def test_godaddy_account_base_url_ote() -> None:
    account = GoDaddyAccount(
        name="x", access_token="t", api_key=None, api_secret=None, environment="ote"
    )
    assert account.base_url == "https://api.ote-godaddy.com"


def test_resolve_godaddy_account_honors_explicit_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "custom-name"
    workspace.mkdir()
    (workspace / "godaddy.env").write_text("GD_ACCESS_TOKEN=custom-token\n", encoding="utf-8")
    accounts = discover_godaddy_accounts(tmp_path)

    resolved = resolve_godaddy_account(default_account(), accounts, workspace="custom-name")

    assert resolved.name == "custom-name"
    assert resolved.access_token == "custom-token"


def test_resolve_godaddy_account_falls_back_to_default_without_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "custom-name"
    workspace.mkdir()
    (workspace / "godaddy.env").write_text("GD_ACCESS_TOKEN=custom-token\n", encoding="utf-8")
    accounts = discover_godaddy_accounts(tmp_path)

    resolved = resolve_godaddy_account(default_account(), accounts)

    assert resolved.name == "default"


def test_resolve_godaddy_account_falls_back_to_default_for_unknown_workspace(
    tmp_path: Path,
) -> None:
    resolved = resolve_godaddy_account(default_account(), (), workspace="unknown")
    assert resolved.name == "default"
