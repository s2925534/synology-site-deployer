from __future__ import annotations

from pathlib import Path

import pytest

from synology_site.errors import SynologySiteError
from synology_site.hdd_db import HDD_DB_SCRIPT_FILES, fetch_hdd_db_files


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class FakeSession:
    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = files or {}
        self.requested_urls: list[str] = []

    def get(self, url: str, timeout: int | None = None) -> FakeResponse:
        del timeout
        self.requested_urls.append(url)
        for filename, content in self.files.items():
            if url.endswith(filename):
                return FakeResponse(content)
        return FakeResponse("not found", status_code=404)


def test_fetches_and_caches_on_first_call(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    session = FakeSession(
        {"syno_hdd_db.sh": "script content", "syno_hdd_vendor_ids.txt": "vendor content"}
    )

    result = fetch_hdd_db_files("v1.0.0", cache_dir=cache_dir, session=session)

    assert result == {
        "syno_hdd_db.sh": "script content",
        "syno_hdd_vendor_ids.txt": "vendor content",
    }
    assert len(session.requested_urls) == len(HDD_DB_SCRIPT_FILES)
    for filename in HDD_DB_SCRIPT_FILES:
        assert (cache_dir / "v1.0.0" / filename).is_file()


def test_uses_cache_without_any_network_call_on_second_call(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    version_dir = cache_dir / "v1.0.0"
    version_dir.mkdir(parents=True)
    (version_dir / "syno_hdd_db.sh").write_text("cached script", encoding="utf-8")
    (version_dir / "syno_hdd_vendor_ids.txt").write_text("cached vendor", encoding="utf-8")
    session = FakeSession()  # would 404 on everything -- must not be called

    result = fetch_hdd_db_files("v1.0.0", cache_dir=cache_dir, session=session)

    assert result == {"syno_hdd_db.sh": "cached script", "syno_hdd_vendor_ids.txt": "cached vendor"}
    assert session.requested_urls == []


def test_refetches_if_cache_is_incomplete(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    version_dir = cache_dir / "v1.0.0"
    version_dir.mkdir(parents=True)
    (version_dir / "syno_hdd_db.sh").write_text("cached script", encoding="utf-8")
    # syno_hdd_vendor_ids.txt deliberately missing -- cache is incomplete
    session = FakeSession(
        {"syno_hdd_db.sh": "fresh script", "syno_hdd_vendor_ids.txt": "fresh vendor"}
    )

    result = fetch_hdd_db_files("v1.0.0", cache_dir=cache_dir, session=session)

    assert result == {"syno_hdd_db.sh": "fresh script", "syno_hdd_vendor_ids.txt": "fresh vendor"}
    assert len(session.requested_urls) == len(HDD_DB_SCRIPT_FILES)


def test_raises_on_http_error(tmp_path: Path) -> None:
    session = FakeSession({})  # every URL 404s

    with pytest.raises(SynologySiteError, match="Failed to fetch"):
        fetch_hdd_db_files("v1.0.0", cache_dir=tmp_path / "cache", session=session)


def test_different_versions_cache_independently(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    session = FakeSession({"syno_hdd_db.sh": "v1 script", "syno_hdd_vendor_ids.txt": "v1 vendor"})
    fetch_hdd_db_files("v1.0.0", cache_dir=cache_dir, session=session)

    session2 = FakeSession(
        {"syno_hdd_db.sh": "v2 script", "syno_hdd_vendor_ids.txt": "v2 vendor"}
    )
    result_v2 = fetch_hdd_db_files("v2.0.0", cache_dir=cache_dir, session=session2)

    assert result_v2["syno_hdd_db.sh"] == "v2 script"
    assert (cache_dir / "v1.0.0" / "syno_hdd_db.sh").read_text(encoding="utf-8") == "v1 script"
