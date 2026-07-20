import json

import pytest

from synology_site.errors import SynologySiteError
from synology_site.port_allocator import (
    choose_port,
    describe_port_conflict,
    find_available_port,
    parse_used_ports,
)
from synology_site.ssh_client import RemoteCommandResult


def test_parse_used_ports_from_docker_and_ss() -> None:
    docker_output = "0.0.0.0:5051->5000/tcp, [::]:5052->5000/tcp\n"
    ss_output = "LISTEN 0 128 0.0.0.0:5053 0.0.0.0:*\n"

    assert parse_used_ports(docker_output, ss_output) == {5051, 5052, 5053}


def test_choose_port_selects_first_free_port() -> None:
    assert choose_port(5050, 5053, {5050, 5051}) == 5052


def test_choose_port_fails_when_range_full() -> None:
    with pytest.raises(SynologySiteError, match="No available port"):
        choose_port(5050, 5051, {5050, 5051})


def test_describe_port_conflict_live_use_wins_over_registry() -> None:
    message = describe_port_conflict(
        5051, used_ports={5051}, registered={5051: "other.example.com"}, domain="new.example.com"
    )
    assert message == "Requested port 5051 is already in use on the NAS"


def test_describe_port_conflict_flags_stopped_but_registered_site() -> None:
    message = describe_port_conflict(
        5051, used_ports=set(), registered={5051: "other.example.com"}, domain="new.example.com"
    )
    assert message is not None
    assert "other.example.com" in message
    assert "nothing is currently running on it" in message


def test_describe_port_conflict_allows_same_domain_reuse() -> None:
    message = describe_port_conflict(
        5051, used_ports=set(), registered={5051: "same.example.com"}, domain="same.example.com"
    )
    assert message is None


def test_describe_port_conflict_none_when_free() -> None:
    assert describe_port_conflict(5051, used_ports=set(), registered={}, domain=None) is None


class _FakeSSHWithMarkers:
    """Minimal SSH stub covering exactly what `find_available_port` needs: a docker-daemon
    probe, the three live port-scan commands, and a marker `find`/`cat` pair per entry in
    `markers` (keyed by the marker file's remote path)."""

    def __init__(self, *, markers: dict[str, dict[str, object]]) -> None:
        self.markers = markers

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def run(self, command: str, *, check: bool = False, timeout: int | None = None):
        del timeout
        exit_code, stdout = 0, ""
        if command == "command -v docker":
            stdout = "docker\n"
        elif command.startswith("find "):
            stdout = "\n".join(self.markers)
        elif command.startswith("cat "):
            path = command[len("cat ") :]
            if path in self.markers:
                stdout = json.dumps(self.markers[path])
            else:
                exit_code = 1
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError(f"command failed: {command}")
        return result


def test_find_available_port_rejects_port_registered_to_another_stopped_site() -> None:
    ssh = _FakeSSHWithMarkers(
        markers={
            "/volume1/docker/other-example-com/.synology-site.json": {
                "domain": "other.example.com",
                "port": 5101,
            },
        }
    )

    with pytest.raises(SynologySiteError, match="other.example.com"):
        find_available_port(
            ssh,
            start=5050,
            end=5999,
            requested=5101,
            docker_root="/volume1/docker",
            domain="new.example.com",
        )


def test_find_available_port_allows_redeploy_onto_own_registered_port() -> None:
    ssh = _FakeSSHWithMarkers(
        markers={
            "/volume1/docker/app-example-com/.synology-site.json": {
                "domain": "app.example.com",
                "port": 5101,
            },
        }
    )

    assert (
        find_available_port(
            ssh,
            start=5050,
            end=5999,
            requested=5101,
            docker_root="/volume1/docker",
            domain="app.example.com",
        )
        == 5101
    )


def test_find_available_port_ignores_docker_root_when_omitted() -> None:
    ssh = _FakeSSHWithMarkers(markers={})

    assert find_available_port(ssh, start=5050, end=5999, requested=5060) == 5060
