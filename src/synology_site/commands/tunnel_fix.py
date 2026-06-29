from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass

import typer
from rich.prompt import Confirm

from synology_site.cloudflare.manual_instructions import build_manual_instructions
from synology_site.commands.check_nas import default_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.errors import SynologySiteError
from synology_site.output import console, ok, warn
from synology_site.ssh_client import SSHClient


@dataclass(frozen=True)
class CloudflaredContainer:
    name: str
    image: str
    status: str

    @property
    def running(self) -> bool:
        return self.status.lower().startswith("up")


SSHFactory = Callable[[Settings, str | None], SSHClient]


def cloudflare_instructions(domain: str, port: int = typer.Option(..., "--port")) -> None:
    try:
        settings = load_config()
        instructions = build_manual_instructions(
            domain,
            settings.cf_zone_domain,
            settings.local_base_url_host,
            port,
            settings.cf_tunnel_name,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc
    console.print(instructions)


def parse_cloudflared_containers(output: str) -> list[CloudflaredContainer]:
    containers: list[CloudflaredContainer] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        name, image, status = parts
        if image.startswith("cloudflare/cloudflared"):
            containers.append(CloudflaredContainer(name=name, image=image, status=status))
    return containers


def run_tunnel_fix_autostart(
    settings: Settings,
    *,
    ssh_factory: SSHFactory = default_ssh_factory,
    prompted_password: str | None = None,
    rename_random: bool = False,
) -> list[CloudflaredContainer]:
    with ssh_factory(settings, prompted_password) as ssh:
        result = ssh.run(
            "docker ps -a --filter ancestor=cloudflare/cloudflared "
            "--format '{{.Names}}\\t{{.Image}}\\t{{.Status}}'",
            check=True,
        )
        containers = parse_cloudflared_containers(result.stdout)
        if not containers:
            warn("No cloudflared containers found")
            return []

        selected = next((item for item in containers if item.name == "cloudflared"), containers[0])
        target_name = selected.name
        if selected.name != "cloudflared" and rename_random:
            ssh.run(f"docker stop {selected.name}", check=False)
            ssh.run(f"docker rename {selected.name} cloudflared", check=True)
            target_name = "cloudflared"

        ssh.run(f"docker update --restart unless-stopped {target_name}", check=True)
        if not selected.running or target_name == "cloudflared":
            ssh.run(f"docker start {target_name}", check=False)
        return containers


def tunnel_fix_autostart() -> None:
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        rename_random = Confirm.ask(
            "Rename the selected cloudflared container to cloudflared if needed?",
            default=False,
        )
        containers = run_tunnel_fix_autostart(
            settings,
            prompted_password=prompted_password,
            rename_random=rename_random,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    for container in containers:
        ok(f"Found {container.name}: {container.status}")


def set_autostart(domain: str) -> None:
    typer.echo(f"Set autostart for {domain}")
