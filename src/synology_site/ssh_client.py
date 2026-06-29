from __future__ import annotations

import base64
import shlex
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
            msg = f"SSH connection to {self.host}:{self.port} failed"
            raise SynologySiteError(msg) from exc
        self._client = client

    def run(
        self,
        command: str,
        *,
        check: bool = False,
        timeout: int | None = None,
    ) -> RemoteCommandResult:
        client = self._require_client()
        try:
            _stdin, stdout_stream, stderr_stream = client.exec_command(command, timeout=timeout)
            if self.password and "sudo -S" in command:
                _stdin.write(f"{self.password}\n")
                _stdin.flush()
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
            try:
                encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
                quoted_path = shlex.quote(remote_path)
                quoted_payload = shlex.quote(encoded)
                self.run(f"printf %s {quoted_payload} | base64 -d > {quoted_path}", check=True)
            except Exception as fallback_exc:  # noqa: BLE001
                msg = f"Failed to upload remote file: {remote_path}"
                raise SynologySiteError(msg) from fallback_exc

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _require_client(self) -> Any:
        if self._client is None:
            raise SynologySiteError("SSH client is not connected")
        return self._client
