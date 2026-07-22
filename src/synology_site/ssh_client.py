from __future__ import annotations

import base64
import os
import shlex
import shutil
import socket
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import paramiko

from synology_site.errors import SynologySiteError


@dataclass(frozen=True)
class RemoteCommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class ParamikoClientFactory(Protocol):
    def __call__(self) -> Any:
        pass


ProcessFactory = Callable[..., subprocess.Popen[Any]]


class SSHClient:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        *,
        key_path: str | None = None,
        password: str | None = None,
        client_factory: ParamikoClientFactory = paramiko.SSHClient,
        timeout: int = 20,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.key_path = key_path
        self.password = password
        self.client_factory = client_factory
        self.timeout = timeout
        self._client: Any | None = None

    def __enter__(self) -> SSHClient:
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def connect(self) -> None:
        client = self.client_factory()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs: dict[str, Any] = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
        }
        if self.key_path:
            connect_kwargs["key_filename"] = str(Path(self.key_path).expanduser())
        elif self.password:
            connect_kwargs["password"] = self.password

        try:
            client.connect(**connect_kwargs)
        except Exception as exc:  # noqa: BLE001
            msg = f"SSH connection to {self.host}:{self.port} failed: {exc}"
            raise SynologySiteError(msg) from exc
        self._client = client

    def run(
        self,
        command: str,
        *,
        check: bool = False,
        timeout: int | None = None,
        stdin: str | None = None,
    ) -> RemoteCommandResult:
        """Runs command over SSH.

        If the command contains "sudo -S" and a password is configured, the
        password is written first, as a login answer. `stdin` (e.g. a token
        for `docker login --password-stdin`) is written after that and the
        write side is then closed, signaling EOF -- required for commands
        that block reading stdin until it's closed. Without an explicit
        `stdin`, the write side is left open as before, since existing
        sudo-only callers don't expect EOF to be signaled.
        """
        client = self._require_client()
        try:
            _stdin, stdout_stream, stderr_stream = client.exec_command(command, timeout=timeout)
            if self.password and "sudo -S" in command:
                _stdin.write(f"{self.password}\n")
                _stdin.flush()
            if stdin is not None:
                _stdin.write(stdin if stdin.endswith("\n") else f"{stdin}\n")
                _stdin.flush()
                _stdin.channel.shutdown_write()
            exit_code = stdout_stream.channel.recv_exit_status()
            stdout = stdout_stream.read().decode("utf-8", errors="replace")
            stderr = stderr_stream.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            msg = f"Remote command failed to execute: {command}"
            raise SynologySiteError(msg) from exc

        result = RemoteCommandResult(
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )
        if check and not result.ok:
            msg = f"Remote command failed with exit code {exit_code}: {command}"
            raise SynologySiteError(msg)
        return result

    def upload_text(self, remote_path: str, content: str) -> None:
        client = self._require_client()
        try:
            with client.open_sftp() as sftp, sftp.file(remote_path, "w") as remote_file:
                remote_file.write(content)
        except Exception:  # noqa: BLE001
            self._upload_bytes_via_stdin(remote_path, content.encode("utf-8"))

    def upload_bytes(self, remote_path: str, content: bytes) -> None:
        client = self._require_client()
        try:
            with client.open_sftp() as sftp, sftp.file(remote_path, "wb") as remote_file:
                remote_file.write(content)
        except Exception:  # noqa: BLE001
            self._upload_bytes_via_stdin(remote_path, content)

    def upload_directory(
        self,
        local_root: Path,
        remote_root: str,
        *,
        ignore: Callable[[Path], bool] | None = None,
    ) -> list[str]:
        """Recursively uploads local_root's contents under remote_root.

        Prefers SFTP; if the server has no SFTP subsystem (some Synology
        setups don't -- confirmed by `open_sftp()` raising), falls back to
        a base64-over-shell upload per file, same as `upload_text`'s
        fallback, just bytes-safe so binary files survive too. Directories
        matched by `ignore` are pruned before descending into them (not
        just filtered after listing), so a large ignored tree (e.g.
        node_modules) doesn't get walked at all. Returns the uploaded
        files' paths relative to local_root.
        """
        client = self._require_client()
        uploaded: list[str] = []
        made_dirs: set[str] = set()
        try:
            sftp: Any = client.open_sftp()
        except Exception:  # noqa: BLE001
            sftp = None
        try:
            for dirpath, dirnames, filenames in os.walk(local_root):
                rel_dir = Path(dirpath).relative_to(local_root)
                dirnames[:] = [
                    d for d in dirnames if not (ignore and ignore(rel_dir / d))
                ]
                for filename in sorted(filenames):
                    rel_path = rel_dir / filename
                    if ignore and ignore(rel_path):
                        continue
                    local_path = Path(dirpath) / filename
                    remote_path = f"{remote_root}/{rel_path.as_posix()}"
                    remote_dir = str(Path(remote_path).parent.as_posix())
                    if sftp is not None:
                        try:
                            if remote_dir not in made_dirs:
                                self._sftp_mkdirs(sftp, remote_dir)
                                made_dirs.add(remote_dir)
                            sftp.put(str(local_path), remote_path)
                            uploaded.append(rel_path.as_posix())
                            continue
                        except Exception:  # noqa: BLE001
                            sftp = None  # stop retrying SFTP; fall back for the rest too
                    self._shell_upload_file(local_path, remote_path)
                    uploaded.append(rel_path.as_posix())
        finally:
            if sftp is not None:
                sftp.close()
        return uploaded

    def _shell_upload_file(self, local_path: Path, remote_path: str) -> None:
        self._upload_bytes_via_stdin(remote_path, local_path.read_bytes())

    def _upload_bytes_via_stdin(self, remote_path: str, content: bytes) -> None:
        """Writes content to remote_path via `base64 -d`, streamed over stdin.

        Unlike embedding the base64 payload directly in the command line
        (fine for small files, but a ~125KB file already overflows some
        shells'/channels' argument-length limits), this has no size limit
        tied to command-line length -- content streams through the
        channel's stdin instead of argv.
        """
        client = self._require_client()
        quoted_dir = shlex.quote(str(Path(remote_path).parent.as_posix()))
        self.run(f"mkdir -p {quoted_dir}", check=True)
        quoted_path = shlex.quote(remote_path)
        try:
            stdin, stdout, stderr = client.exec_command(f"base64 -d > {quoted_path}")
            encoded = base64.b64encode(content)
            chunk_size = 32768
            for i in range(0, len(encoded), chunk_size):
                stdin.write(encoded[i : i + chunk_size])
            stdin.flush()
            stdin.channel.shutdown_write()
            exit_code = stdout.channel.recv_exit_status()
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to upload remote file via stdin: {remote_path}"
            raise SynologySiteError(msg) from exc
        if exit_code != 0:
            err = stderr.read().decode("utf-8", errors="replace")
            msg = f"Failed to upload remote file via stdin: {remote_path}: {err}"
            raise SynologySiteError(msg)

    def _sftp_mkdirs(self, sftp: Any, remote_dir: str) -> None:
        if not remote_dir or remote_dir == ".":
            return
        current = ""
        for part in remote_dir.strip("/").split("/"):
            current += f"/{part}"
            try:
                sftp.stat(current)
            except FileNotFoundError:
                sftp.mkdir(current)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _require_client(self) -> Any:
        if self._client is None:
            raise SynologySiteError("SSH client is not connected")
        return self._client


class CloudflareAccessSSHClient(SSHClient):
    def __init__(
        self,
        access_hostname: str,
        local_port: int,
        username: str,
        *,
        key_path: str | None = None,
        password: str | None = None,
        cloudflared_path: str = "cloudflared",
        client_factory: ParamikoClientFactory = paramiko.SSHClient,
        process_factory: ProcessFactory = subprocess.Popen,
        timeout: int = 20,
    ) -> None:
        self.access_hostname = access_hostname
        self.requested_local_port = local_port
        self.cloudflared_path = cloudflared_path
        self.process_factory = process_factory
        self._process: subprocess.Popen[Any] | None = None
        super().__init__(
            "127.0.0.1",
            local_port,
            username,
            key_path=key_path,
            password=password,
            client_factory=client_factory,
            timeout=timeout,
        )

    def connect(self) -> None:
        if self.cloudflared_path == "cloudflared" and shutil.which(self.cloudflared_path) is None:
            msg = "cloudflared is required for SSH_ACCESS_HOSTNAME but was not found on PATH"
            raise SynologySiteError(msg)
        if self.requested_local_port <= 0:
            self.port = _find_free_local_port()
        try:
            self._start_proxy()
            self._wait_for_proxy()
            super().connect()
        except Exception:
            self._stop_proxy()
            raise

    def close(self) -> None:
        super().close()
        self._stop_proxy()

    def _stop_proxy(self) -> None:
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            self._process = None

    def _start_proxy(self) -> None:
        command = [
            self.cloudflared_path,
            "access",
            "tcp",
            "--hostname",
            self.access_hostname,
            "--url",
            f"localhost:{self.port}",
        ]
        try:
            self._process = self.process_factory(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            msg = "cloudflared is required for SSH_ACCESS_HOSTNAME but was not found"
            raise SynologySiteError(msg) from exc
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to start cloudflared access proxy for {self.access_hostname}"
            raise SynologySiteError(msg) from exc

    def _wait_for_proxy(self) -> None:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                msg = f"cloudflared access proxy exited early for {self.access_hostname}"
                raise SynologySiteError(msg)
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.2)
        msg = f"Timed out waiting for cloudflared access proxy on localhost:{self.port}"
        raise SynologySiteError(msg)


def _find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
