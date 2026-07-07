from __future__ import annotations

import json

import requests

from synology_site.commands.health import check_health_for_targets
from synology_site.config import Settings
from synology_site.errors import SynologySiteError
from synology_site.nas.target import NasTarget
from synology_site.ssh_client import RemoteCommandResult


def settings() -> Settings:
    return Settings(
        nas_host="192.0.2.10",
        nas_port=22,
        nas_user="deploy",
        nas_docker_root="/volume1/docker",
        nas_ssh_key_path=None,
        nas_ssh_password="secret",
        local_base_url_host="192.0.2.10",
        default_start_port=5050,
        default_end_port=5999,
        default_framework="flask",
        restart_policy="unless-stopped",
        cf_api_token=None,
        cf_account_id=None,
        cf_zone_id=None,
        cf_zone_domain="example.com",
        cf_tunnel_id=None,
        cf_tunnel_name="my-nas-tunnel",
        db_mode="none",
        db_type="mariadb",
        db_image="mariadb:11",
        db_password_length=32,
        db_publish_port=False,
        db_host_port=None,
        allow_overwrite=False,
        dry_run=False,
    )


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeSSH:
    def __init__(self, markers: list[dict[str, object]], *, unreachable: bool = False) -> None:
        self.markers = markers
        self.unreachable = unreachable

    def __enter__(self) -> FakeSSH:
        if self.unreachable:
            raise SynologySiteError("ssh failed")
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def run(
        self,
        command: str,
        *,
        check: bool = False,
        timeout: int | None = None,
    ) -> RemoteCommandResult:
        del timeout
        marker_paths = [
            f"/volume1/docker/site-{index}/.synology-site.json"
            for index in range(len(self.markers))
        ]
        if command.startswith("find "):
            return RemoteCommandResult(command, 0, "\n".join(marker_paths), "")
        for index, marker_path in enumerate(marker_paths):
            if command == f"cat {marker_path}":
                return RemoteCommandResult(command, 0, json.dumps(self.markers[index]), "")
        result = RemoteCommandResult(command, 1, "", "unexpected")
        if check and not result.ok:
            raise SynologySiteError("command failed")
        return result


def test_check_health_for_targets_reports_ok_and_failed_sites() -> None:
    fake = FakeSSH(
        [
            {"domain": "ok.example.com", "port": 5050},
            {"domain": "bad.example.com", "port": 5051},
        ]
    )

    def health_get(url: str, timeout: int) -> FakeResponse:
        del timeout
        return FakeResponse(200 if ":5050" in url else 503)

    results = check_health_for_targets(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
        health_get=health_get,
    )

    assert [result.ok for result in results] == [True, False]
    assert results[0].url == "http://192.0.2.10:5050/health"
    assert results[1].status == 503


def test_check_health_for_targets_reports_marker_without_port() -> None:
    fake = FakeSSH([{"domain": "proxy.example.com", "port": None}])

    results = check_health_for_targets(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
    )

    assert results[0].ok is False
    assert results[0].error == "no port in marker"
    assert results[0].url is None


def test_check_health_for_targets_reports_request_errors() -> None:
    fake = FakeSSH([{"domain": "app.example.com", "port": 5050}])

    def health_get(url: str, timeout: int) -> FakeResponse:
        del url, timeout
        raise requests.ConnectionError("refused")

    results = check_health_for_targets(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
        health_get=health_get,
    )

    assert results[0].ok is False
    assert "refused" in str(results[0].error)


def test_check_health_for_targets_keeps_going_when_target_unreachable() -> None:
    base = settings()
    other = NasTarget(
        name="other",
        host="203.0.113.5",
        port=22,
        user="deploy",
        ssh_key_path=None,
        ssh_password="secret",
        docker_root="/volume1/docker",
        local_base_url_host="203.0.113.5",
        default_start_port=5050,
        default_end_port=5999,
    )

    def ssh_factory(connection_settings: Settings, _password: str | None) -> FakeSSH:
        if connection_settings.nas_host == "203.0.113.5":
            return FakeSSH([], unreachable=True)
        return FakeSSH([{"domain": "app.example.com", "port": 5050}])

    results = check_health_for_targets(
        base,
        (base.default_nas_target, other),
        ssh_factory=ssh_factory,
        health_get=lambda _url, timeout: FakeResponse(200),
    )

    assert len(results) == 2
    assert results[0].ok is True
    assert results[1].target_name == "other"
    assert results[1].domain == "*"
    assert "target unreachable" in str(results[1].error)
