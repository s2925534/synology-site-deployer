from __future__ import annotations

import json

from synology_site.commands.list_sites import list_sites_across_targets
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


class FakeSSH:
    def __init__(self, host: str, markers: list[dict[str, object]]) -> None:
        self.host = host
        self.markers = markers

    def __enter__(self) -> FakeSSH:
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def run(self, command: str, *, check: bool = False, timeout: int | None = None):
        del check, timeout
        if command.startswith("find "):
            paths = "\n".join(
                f"/volume1/docker/site-{i}/.synology-site.json" for i in range(len(self.markers))
            )
            return RemoteCommandResult(command, 0, paths, "")
        for i, marker in enumerate(self.markers):
            if command == f"cat /volume1/docker/site-{i}/.synology-site.json":
                return RemoteCommandResult(command, 0, json.dumps(marker), "")
        return RemoteCommandResult(command, 1, "", "not found")


def test_list_sites_across_targets_aggregates_multiple_targets() -> None:
    per_host_markers = {
        "192.0.2.10": [{"domain": "a.example.com", "port": 5051, "slug": "a-example-com"}],
        "203.0.113.5": [{"domain": "b.clienta.dev", "port": 5052, "slug": "b-clienta-dev"}],
    }

    def ssh_factory(passed_settings: Settings, _password: object) -> FakeSSH:
        return FakeSSH(passed_settings.nas_host, per_host_markers[passed_settings.nas_host])

    clienta_target = NasTarget(
        name="clienta",
        host="203.0.113.5",
        port=22,
        user="deploy",
        ssh_key_path=None,
        ssh_password="secret",
        docker_root="/volume1/docker",
        local_base_url_host="192.0.2.10",
        default_start_port=5050,
        default_end_port=5999,
    )

    results = list_sites_across_targets(
        settings(),
        (settings().default_nas_target, clienta_target),
        ssh_factory=ssh_factory,
        password_prompt=lambda target: None,
    )

    assert results["default"] == per_host_markers["192.0.2.10"]
    assert results["clienta"] == per_host_markers["203.0.113.5"]


def test_list_sites_across_targets_isolates_unreachable_target() -> None:
    def ssh_factory(passed_settings: Settings, _password: object):
        if passed_settings.nas_host == "203.0.113.5":
            raise SynologySiteError("Docker is not available on the NAS")
        return FakeSSH(passed_settings.nas_host, [])

    broken_target = NasTarget(
        name="broken",
        host="203.0.113.5",
        port=22,
        user="deploy",
        ssh_key_path=None,
        ssh_password="secret",
        docker_root="/volume1/docker",
        local_base_url_host="192.0.2.10",
        default_start_port=5050,
        default_end_port=5999,
    )

    results = list_sites_across_targets(
        settings(),
        (settings().default_nas_target, broken_target),
        ssh_factory=ssh_factory,
        password_prompt=lambda target: None,
    )

    assert results["default"] == []
    assert "unreachable" in results["broken"]
