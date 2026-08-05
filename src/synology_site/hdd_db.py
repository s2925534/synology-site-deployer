from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from synology_site.errors import SynologySiteError

HDD_DB_REPO = "007revad/Synology_HDD_db"
DEFAULT_HDD_DB_VERSION = "v3.6.137"
HDD_DB_SCRIPT_FILES = ("syno_hdd_db.sh", "syno_hdd_vendor_ids.txt")
DEFAULT_CACHE_DIR = Path("vendor/synology_hdd_db")


def fetch_hdd_db_files(
    version: str = DEFAULT_HDD_DB_VERSION,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    session: Any = requests,
) -> dict[str, str]:
    """Returns {filename: content} for a pinned 007revad/Synology_HDD_db release.

    Reads from `cache_dir/<version>/` first if a complete cached copy is already there -- no
    network call, and no dependency on the upstream repo still existing/being reachable. Only
    hits the network on a cache miss, then writes the cache for next time. Always pinned to an
    explicit tag, never a moving branch, so what gets used is exactly what was reviewed before
    first use, not whatever happens to be on `main` right now.
    """
    version_dir = cache_dir / version
    cached = {
        filename: (version_dir / filename).read_text(encoding="utf-8")
        for filename in HDD_DB_SCRIPT_FILES
        if (version_dir / filename).is_file()
    }
    if len(cached) == len(HDD_DB_SCRIPT_FILES):
        return cached

    fetched: dict[str, str] = {}
    for filename in HDD_DB_SCRIPT_FILES:
        url = f"https://raw.githubusercontent.com/{HDD_DB_REPO}/{version}/{filename}"
        try:
            response = session.get(url, timeout=15)
        except requests.RequestException as exc:
            msg = f"Failed to fetch {filename} from {HDD_DB_REPO}@{version}: {exc}"
            raise SynologySiteError(msg) from exc
        if response.status_code != 200:
            msg = (
                f"Failed to fetch {filename} from {HDD_DB_REPO}@{version}: "
                f"HTTP {response.status_code} -- check the version tag exists"
            )
            raise SynologySiteError(msg)
        fetched[filename] = response.text

    version_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in fetched.items():
        (version_dir / filename).write_text(content, encoding="utf-8")

    return fetched
