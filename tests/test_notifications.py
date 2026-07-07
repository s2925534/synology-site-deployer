from __future__ import annotations

from synology_site.config import Settings
from synology_site.notifications import send_webhook_notification


def settings(**overrides: object) -> Settings:
    base = {
        "nas_host": "192.0.2.10",
        "nas_port": 22,
        "nas_user": "deploy",
        "nas_docker_root": "/volume1/docker",
        "nas_ssh_key_path": None,
        "nas_ssh_password": "secret",
        "local_base_url_host": "192.0.2.10",
        "default_start_port": 5050,
        "default_end_port": 5999,
        "default_framework": "flask",
        "restart_policy": "unless-stopped",
        "cf_api_token": None,
        "cf_account_id": None,
        "cf_zone_id": None,
        "cf_zone_domain": "example.com",
        "cf_tunnel_id": None,
        "cf_tunnel_name": "my-nas-tunnel",
        "db_mode": "none",
        "db_type": "mariadb",
        "db_image": "mariadb:11",
        "db_password_length": 32,
        "db_publish_port": False,
        "db_host_port": None,
        "allow_overwrite": False,
        "dry_run": False,
    }
    base.update(overrides)
    return Settings(**base)


class FakeResponse:
    status_code = 204


def test_send_webhook_notification_skips_when_unconfigured() -> None:
    calls: list[object] = []

    sent = send_webhook_notification(
        settings(),
        event="success",
        command="deploy",
        title="Deploy succeeded",
        detail="ok",
        post=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert sent is False
    assert calls == []


def test_send_webhook_notification_posts_slack_and_discord_compatible_payload() -> None:
    calls: list[dict[str, object]] = []

    def post(url: str, *, json: dict[str, object], timeout: int) -> FakeResponse:
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    sent = send_webhook_notification(
        settings(notify_webhook_url="https://hooks.example.test/deploy"),
        event="success",
        command="deploy",
        title="Deploy succeeded: app.example.com",
        detail="Project folder: /volume1/docker/app",
        post=post,
    )

    assert sent is True
    assert calls[0]["url"] == "https://hooks.example.test/deploy"
    payload = calls[0]["json"]
    assert isinstance(payload, dict)
    assert "Deploy succeeded: app.example.com" in str(payload["text"])
    assert payload["content"] == payload["text"]
    assert payload["event"] == "success"


def test_send_webhook_notification_respects_event_filter() -> None:
    calls: list[object] = []

    sent = send_webhook_notification(
        settings(
            notify_webhook_url="https://hooks.example.test/deploy",
            notify_webhook_events="failure",
        ),
        event="success",
        command="deploy",
        title="Deploy succeeded",
        detail="ok",
        post=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert sent is False
    assert calls == []
