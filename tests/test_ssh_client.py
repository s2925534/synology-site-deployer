from __future__ import annotations

from io import BytesIO, StringIO
from typing import Any

import pytest

from synology_site.errors import SynologySiteError
from synology_site.ssh_client import CloudflareAccessSSHClient, SSHClient


class FakeChannel:
    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code

    def recv_exit_status(self) -> int:
        return self.exit_code


class FakeStream(BytesIO):
    def __init__(self, text: str, exit_code: int = 0) -> None:
        super().__init__(text.encode())
        self.channel = FakeChannel(exit_code)


class FakeSFTP:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.current_path: str | None = None
        self.buffer: StringIO | None = None

    def __enter__(self) -> FakeSFTP:
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.current_path is not None and self.buffer is not None:
            self.files[self.current_path] = self.buffer.getvalue()

    def file(self, path: str, mode: str) -> FakeSFTP:
        assert mode == "w"
        self.current_path = path
        self.buffer = StringIO()
        return self

    def write(self, content: str) -> None:
        assert self.buffer is not None
        self.buffer.write(content)


class FakeSSH:
    def __init__(self) -> None:
        self.connected_kwargs: dict[str, Any] | None = None
        self.closed = False
        self.commands: list[str] = []
        self.sftp = FakeSFTP()

    def set_missing_host_key_policy(self, _policy: object) -> None:
        pass

    def connect(self, **kwargs: Any) -> None:
        self.connected_kwargs = kwargs

    def exec_command(
        self,
        command: str,
        timeout: int | None = None,
    ) -> tuple[None, FakeStream, FakeStream]:
        del timeout
        self.commands.append(command)
        return None, FakeStream("hello\n", 0), FakeStream("", 0)

    def open_sftp(self) -> FakeSFTP:
        return self.sftp

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: int | None = None) -> int:
        del timeout
        return 0


def test_ssh_client_connects_with_key() -> None:
    fake = FakeSSH()
    client = SSHClient(
        "nas.local",
        22,
        "deploy",
        key_path="~/.ssh/id_ed25519",
        client_factory=lambda: fake,
    )

    client.connect()

    assert fake.connected_kwargs is not None
    assert fake.connected_kwargs["hostname"] == "nas.local"
    assert fake.connected_kwargs["username"] == "deploy"
    assert fake.connected_kwargs["key_filename"].endswith(".ssh/id_ed25519")
    assert "password" not in fake.connected_kwargs


def test_ssh_client_connects_with_password() -> None:
    fake = FakeSSH()
    client = SSHClient("nas.local", 22, "deploy", password="secret", client_factory=lambda: fake)

    client.connect()

    assert fake.connected_kwargs is not None
    assert fake.connected_kwargs["password"] == "secret"
    assert "key_filename" not in fake.connected_kwargs


def test_ssh_client_runs_command() -> None:
    fake = FakeSSH()
    client = SSHClient("nas.local", 22, "deploy", client_factory=lambda: fake)
    client.connect()

    result = client.run("docker ps")

    assert result.ok is True
    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert fake.commands == ["docker ps"]


def test_ssh_client_uploads_text() -> None:
    fake = FakeSSH()
    client = SSHClient("nas.local", 22, "deploy", client_factory=lambda: fake)
    client.connect()

    client.upload_text("/volume1/docker/demo/app.py", "print('ok')\n")

    assert fake.sftp.files["/volume1/docker/demo/app.py"] == "print('ok')\n"


def test_ssh_client_requires_connection() -> None:
    client = SSHClient("nas.local", 22, "deploy")

    with pytest.raises(SynologySiteError, match="not connected"):
        client.run("docker ps")


def test_cloudflare_access_ssh_client_starts_proxy_and_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_ssh = FakeSSH()
    fake_process = FakeProcess()
    commands: list[list[str]] = []

    def process_factory(command: list[str], **_kwargs: object) -> FakeProcess:
        commands.append(command)
        return fake_process

    class FakeSocket:
        def __enter__(self) -> FakeSocket:
            return self

        def __exit__(self, *_exc: object) -> None:
            pass

    monkeypatch.setattr(
        "synology_site.ssh_client.socket.create_connection",
        lambda _address, timeout: FakeSocket(),
    )

    client = CloudflareAccessSSHClient(
        "nas-ssh.example.com",
        9210,
        "deploy",
        password="secret",
        cloudflared_path="/usr/local/bin/cloudflared",
        client_factory=lambda: fake_ssh,
        process_factory=process_factory,
    )

    client.connect()
    client.close()

    assert commands == [
        [
            "/usr/local/bin/cloudflared",
            "access",
            "tcp",
            "--hostname",
            "nas-ssh.example.com",
            "--url",
            "localhost:9210",
        ]
    ]
    assert fake_ssh.connected_kwargs is not None
    assert fake_ssh.connected_kwargs["hostname"] == "127.0.0.1"
    assert fake_ssh.connected_kwargs["port"] == 9210
    assert fake_process.terminated is True
