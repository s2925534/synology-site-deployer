from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_LOG_DIR = Path("activity-log")
DEFAULT_LOG_FILENAME = "history.jsonl"


def record_activity(
    action: str,
    *,
    details: dict[str, Any] | None = None,
    log_dir: Path = DEFAULT_LOG_DIR,
    log_filename: str = DEFAULT_LOG_FILENAME,
) -> None:
    """Appends one JSON-lines entry recording a CLI action (create/deploy/update/etc.).

    Best-effort only, by design: a logging failure (read-only filesystem, disk full) must never
    turn an otherwise successful deployment into a reported failure, so any error here is
    swallowed rather than raised. See activity-log/README.md for the log format -- that file is
    the one thing in this directory committed to git; the growing *.jsonl log itself is
    gitignored, so day-to-day history never bloats the repo.
    """
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
        }
        entry.update(details or {})
        with (log_dir / log_filename).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
    except OSError:
        pass
