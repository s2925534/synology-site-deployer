import pytest

from synology_site.errors import SynologySiteError
from synology_site.port_allocator import choose_port, parse_used_ports


def test_parse_used_ports_from_docker_and_ss() -> None:
    docker_output = "0.0.0.0:5051->5000/tcp, [::]:5052->5000/tcp\n"
    ss_output = "LISTEN 0 128 0.0.0.0:5053 0.0.0.0:*\n"

    assert parse_used_ports(docker_output, ss_output) == {5051, 5052, 5053}


def test_choose_port_selects_first_free_port() -> None:
    assert choose_port(5050, 5053, {5050, 5051}) == 5052


def test_choose_port_fails_when_range_full() -> None:
    with pytest.raises(SynologySiteError, match="No available port"):
        choose_port(5050, 5051, {5050, 5051})
