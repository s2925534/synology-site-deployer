from __future__ import annotations

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
