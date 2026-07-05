from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

from synology_site.ssh_client import SSHClient
from synology_site.upload_filter import build_ignore_matcher


class FakeSFTP:
    def __init__(self) -> None:
        self.dirs: set[str] = {"/"}
        self.uploaded: dict[str, str] = {}
        self.closed = False

    def stat(self, path: str) -> None:
        if path not in self.dirs:
            raise FileNotFoundError(path)

    def mkdir(self, path: str) -> None:
        self.dirs.add(path)

    def put(self, local_path: str, remote_path: str) -> None:
        self.uploaded[remote_path] = Path(local_path).read_text(encoding="utf-8")

    def close(self) -> None:
        self.closed = True


class FakeSSH:
    def __init__(self) -> None:
        self.sftp = FakeSFTP()

    def set_missing_host_key_policy(self, _policy: object) -> None:
        pass

    def connect(self, **_kwargs: Any) -> None:
        pass

    def open_sftp(self) -> FakeSFTP:
        return self.sftp

    def close(self) -> None:
        pass


def _make_tree(root: Path) -> None:
    (root / "apps" / "web").mkdir(parents=True)
    (root / "apps" / "web" / "index.ts").write_text("web entry\n")
    (root / "apps" / "web" / "node_modules").mkdir()
    (root / "apps" / "web" / "node_modules" / "dep.js").write_text("should be skipped\n")
    (root / "packages" / "core").mkdir(parents=True)
    (root / "packages" / "core" / "index.ts").write_text("core entry\n")
    (root / "README.md").write_text("docs\n")
    (root / ".env").write_text("SECRET=should_not_upload\n")


def test_upload_directory_uploads_files_and_skips_ignored(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    fake = FakeSSH()
    client = SSHClient("nas.local", 22, "deploy", client_factory=lambda: fake)
    client.connect()

    ignore = build_ignore_matcher(["node_modules", "*.md", ".env"])
    uploaded = client.upload_directory(tmp_path, "/volume1/docker/proj/repo", ignore=ignore)

    assert "apps/web/index.ts" in uploaded
    assert "packages/core/index.ts" in uploaded
    assert not any("node_modules" in p for p in uploaded)
    assert "README.md" not in uploaded
    assert ".env" not in uploaded

    assert fake.sftp.uploaded["/volume1/docker/proj/repo/apps/web/index.ts"] == "web entry\n"
    assert fake.sftp.uploaded["/volume1/docker/proj/repo/packages/core/index.ts"] == "core entry\n"
    assert not any("node_modules" in p for p in fake.sftp.uploaded)


def test_upload_directory_creates_nested_remote_dirs(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    fake = FakeSSH()
    client = SSHClient("nas.local", 22, "deploy", client_factory=lambda: fake)
    client.connect()

    client.upload_directory(tmp_path, "/volume1/docker/proj/repo", ignore=lambda p: False)

    assert "/volume1/docker/proj/repo/apps/web" in fake.sftp.dirs
    assert "/volume1/docker/proj/repo/packages/core" in fake.sftp.dirs


class FakeChannel:
    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code

    def recv_exit_status(self) -> int:
        return self.exit_code


class FakeStream(BytesIO):
    def __init__(self, text: str = "", exit_code: int = 0) -> None:
        super().__init__(text.encode())
        self.channel = FakeChannel(exit_code)


class FakeStdin:
    """Records bytes written before shutdown_write, like a real channel's stdin."""

    def __init__(self, on_shutdown: Any) -> None:
        self._buffer = bytearray()
        self._on_shutdown = on_shutdown
        self.channel = self

    def write(self, data: bytes) -> None:
        self._buffer.extend(data)

    def flush(self) -> None:
        pass

    def shutdown_write(self) -> None:
        self._on_shutdown(bytes(self._buffer))


class NoSFTPFakeSSH:
    """Simulates a server with no SFTP subsystem -- open_sftp() always fails."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.decoded_uploads: dict[str, bytes] = {}

    def set_missing_host_key_policy(self, _policy: object) -> None:
        pass

    def connect(self, **_kwargs: Any) -> None:
        pass

    def open_sftp(self) -> None:
        raise Exception("Channel closed.")  # noqa: TRY002

    def exec_command(
        self, command: str, timeout: int | None = None
    ) -> tuple[Any, FakeStream, FakeStream]:
        del timeout
        self.commands.append(command)
        if command.startswith("base64 -d > "):
            path = command[len("base64 -d > ") :].strip("'")

            def on_shutdown(encoded: bytes, path: str = path) -> None:
                self.decoded_uploads[path] = base64.b64decode(encoded)

            return FakeStdin(on_shutdown), FakeStream("", 0), FakeStream("", 0)
        return None, FakeStream("", 0), FakeStream("", 0)

    def close(self) -> None:
        pass


def test_upload_directory_falls_back_to_shell_when_sftp_unavailable(tmp_path: Path) -> None:
    (tmp_path / "apps").mkdir()
    (tmp_path / "apps" / "index.ts").write_bytes(b"entry\xff\x00binary-safe\n")
    fake = NoSFTPFakeSSH()
    client = SSHClient("nas.local", 22, "deploy", client_factory=lambda: fake)
    client.connect()

    uploaded = client.upload_directory(
        tmp_path, "/volume1/docker/proj/repo", ignore=lambda p: False
    )

    assert uploaded == ["apps/index.ts"]
    mkdir_cmd = next(c for c in fake.commands if c.startswith("mkdir -p"))
    assert "/volume1/docker/proj/repo/apps" in mkdir_cmd
    remote_path = "/volume1/docker/proj/repo/apps/index.ts"
    assert fake.decoded_uploads[remote_path] == b"entry\xff\x00binary-safe\n"


def test_upload_directory_handles_large_file_via_chunked_stdin(tmp_path: Path) -> None:
    (tmp_path / "big.bin").write_bytes(b"x" * 200_000)
    fake = NoSFTPFakeSSH()
    client = SSHClient("nas.local", 22, "deploy", client_factory=lambda: fake)
    client.connect()

    client.upload_directory(tmp_path, "/volume1/docker/proj/repo", ignore=lambda p: False)

    assert fake.decoded_uploads["/volume1/docker/proj/repo/big.bin"] == b"x" * 200_000
