from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

import typer

from synology_site.config import load_config
from synology_site.database.naming import database_name, database_user
from synology_site.errors import SynologySiteError
from synology_site.naming import db_container_name, domain_to_slug
from synology_site.output import console, next_step, ok
from synology_site.validators import apply_default_site_domain, validate_domain


@dataclass(frozen=True)
class BackupPlanResult:
    domain: str
    output_dir: Path
    files: tuple[Path, ...]


def generate_backup_plan(
    domain: str,
    *,
    output_dir: Path = Path("backup-plans"),
    retention_days: int = 14,
) -> BackupPlanResult:
    domain = validate_domain(domain)
    if retention_days < 1:
        raise SynologySiteError("--retention-days must be at least 1")

    slug = domain_to_slug(domain)
    plan_dir = output_dir / slug
    plan_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "backup.sh": _backup_script(),
        "backup.env.example": _backup_env(domain=domain, retention_days=retention_days),
        "README.md": _readme(domain=domain),
        "crontab.example": _crontab(plan_dir),
        "synology-task-command.txt": _synology_task_command(plan_dir),
    }
    written: list[Path] = []
    for filename, content in files.items():
        path = plan_dir / filename
        path.write_text(content, encoding="utf-8")
        written.append(path)
        if filename == "backup.sh":
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    return BackupPlanResult(domain=domain, output_dir=plan_dir, files=tuple(written))


def _backup_env(*, domain: str, retention_days: int) -> str:
    return (
        f"DOMAIN={domain}\n"
        f"DB_CONTAINER={db_container_name(domain)}\n"
        f"DB_NAME={database_name(domain)}\n"
        f"DB_USER={database_user(domain)}\n"
        "DB_PASSWORD=\n"
        "BACKUP_DIR=./backups\n"
        f"RETENTION_DAYS={retention_days}\n"
        "\n"
        "# Optional S3-compatible upload. Leave empty for local-only backups.\n"
        "S3_ENDPOINT_URL=https://s3.example.com\n"
        "S3_BUCKET=\n"
        "S3_PREFIX=synology-site\n"
        "AWS_ACCESS_KEY_ID=\n"
        "AWS_SECRET_ACCESS_KEY=\n"
    )


def _backup_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/backup.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  echo "Copy backup.env.example to backup.env and fill in DB/S3 values." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

: "${DB_CONTAINER:?DB_CONTAINER is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"

BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
backup_file="$BACKUP_DIR/${DB_NAME}-${timestamp}.sql.gz"

docker exec "$DB_CONTAINER" mariadb-dump \
  --single-transaction \
  --quick \
  -u "$DB_USER" \
  "-p$DB_PASSWORD" \
  "$DB_NAME" | gzip > "$backup_file"

if [[ -n "${S3_BUCKET:-}" ]]; then
  : "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required when S3_BUCKET is set}"
  : "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required when S3_BUCKET is set}"
  endpoint_args=()
  if [[ -n "${S3_ENDPOINT_URL:-}" ]]; then
    endpoint_args=(--endpoint-url "$S3_ENDPOINT_URL")
  fi
  aws "${endpoint_args[@]}" s3 cp \
    "$backup_file" \
    "s3://${S3_BUCKET}/${S3_PREFIX:-synology-site}/${DB_NAME}/$(basename "$backup_file")"
fi

find "$BACKUP_DIR" -name "${DB_NAME}-*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
echo "Backup complete: $backup_file"
"""


def _readme(*, domain: str) -> str:
    return f"""# Backup Plan For `{domain}`

This folder contains a generated MariaDB backup script for a `synology-site create --with-db`
site. It does not contain live credentials.

1. Copy `backup.env.example` to `backup.env`.
2. Fill in `DB_PASSWORD` from the deployed site's generated `.env`.
3. Optionally fill in `S3_BUCKET`, `S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, and
   `AWS_SECRET_ACCESS_KEY` for Backblaze B2, Cloudflare R2, MinIO, or another S3-compatible
   target.
4. Install the AWS CLI wherever this script runs if you enable S3 upload.
5. Schedule `backup.sh` with Synology Task Scheduler or cron.

The script keeps local compressed dumps under `BACKUP_DIR` and deletes old local dumps after
`RETENTION_DAYS`.
"""


def _crontab(plan_dir: Path) -> str:
    resolved = plan_dir.resolve()
    return (
        "# Daily at 02:15 UTC/local system time, depending on the host's cron config.\n"
        f"15 2 * * * {resolved}/backup.sh {resolved}/backup.env\n"
    )


def _synology_task_command(plan_dir: Path) -> str:
    return f"{plan_dir.resolve()}/backup.sh {plan_dir.resolve()}/backup.env\n"


def app(
    domain: str,
    output_dir: Path = typer.Option(Path("backup-plans"), "--output-dir"),  # noqa: B008
    retention_days: int = typer.Option(14, "--retention-days"),
) -> None:
    try:
        settings = load_config()
        domain = apply_default_site_domain(domain, settings.default_site_domain)
        result = generate_backup_plan(
            domain,
            output_dir=output_dir,
            retention_days=retention_days,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Backup Plan")
    ok(f"Generated: {result.output_dir}")
    for path in result.files:
        ok(str(path))
    next_step(
        "Copy backup.env.example to backup.env, fill in credentials, then schedule backup.sh."
    )
