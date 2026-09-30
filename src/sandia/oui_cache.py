"""Optional local cache of the full IEEE OUI (MAC vendor prefix) registry.

`vendors.py` ships a small built-in list of common vendors that works with
zero setup, fully offline. This module lets that list be extended with the
full public IEEE registry (tens of thousands of entries), downloaded once
and cached to a file under the data directory so repeat lookups need no
network access.

Refreshing is explicit (never automatic) and always runs in a background
thread, so a slow or unreachable network never blocks a request. If a
refresh fails for any reason, the existing cache (or the built-in list, if
there's no cache yet) keeps working exactly as before - this is a
convenience layer, never a dependency the app needs to function.
"""

from __future__ import annotations

import csv
import io
import json
import threading
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

OUI_CSV_URL = "https://standards-oui.ieee.org/oui/oui.csv"
CACHE_FILENAME = "oui_cache.json"
REQUEST_TIMEOUT = 30


@dataclass
class CacheStatus:
    cached: bool
    entry_count: int
    fetched_at: str | None
    refreshing: bool
    last_error: str | None


_lock = threading.Lock()
_refreshing = False
_last_error: str | None = None
_memo: dict[str, dict[str, str]] = {}
_memo_meta: dict[str, dict] = {}


def _cache_path(data_dir: Path) -> Path:
    return data_dir / CACHE_FILENAME


def _load_from_disk(data_dir: Path) -> tuple[dict[str, str], dict] | None:
    path = _cache_path(data_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    entries = payload.get("entries", {})
    return entries, {"fetched_at": payload.get("fetched_at"), "entry_count": len(entries)}


def _cached(data_dir: Path) -> tuple[dict[str, str], dict] | None:
    key = str(data_dir)
    if key not in _memo:
        loaded = _load_from_disk(data_dir)
        if loaded is None:
            return None
        _memo[key], _memo_meta[key] = loaded
    return _memo[key], _memo_meta[key]


def lookup(data_dir: Path, prefix: str) -> str | None:
    """Look up a 3-octet OUI prefix (e.g. `AA:BB:CC`) in the cached registry."""
    loaded = _cached(data_dir)
    if loaded is None:
        return None
    entries, _meta = loaded
    return entries.get(prefix)


def status(data_dir: Path) -> CacheStatus:
    loaded = _cached(data_dir)
    return CacheStatus(
        cached=loaded is not None,
        entry_count=loaded[1]["entry_count"] if loaded else 0,
        fetched_at=loaded[1]["fetched_at"] if loaded else None,
        refreshing=_refreshing,
        last_error=_last_error,
    )


def _parse_csv(raw: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(raw)):
        assignment = (row.get("Assignment") or "").strip().upper()
        name = (row.get("Organization Name") or "").strip()
        if len(assignment) != 6 or not name:
            continue
        prefix = ":".join(assignment[i : i + 2] for i in range(0, 6, 2))
        entries[prefix] = name
    return entries


def _do_refresh(data_dir: Path) -> None:
    global _refreshing, _last_error
    try:
        req = urllib.request.Request(OUI_CSV_URL, headers={"User-Agent": "sandia-dhcp-ui"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read().decode("utf-8", errors="replace")

        entries = _parse_csv(raw)
        if not entries:
            raise ValueError("no entries parsed from IEEE OUI download")

        fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
        data_dir.mkdir(parents=True, exist_ok=True)
        final_path = _cache_path(data_dir)
        tmp_path = final_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps({"fetched_at": fetched_at, "entries": entries}))
        tmp_path.replace(final_path)

        key = str(data_dir)
        _memo[key] = entries
        _memo_meta[key] = {"fetched_at": fetched_at, "entry_count": len(entries)}
        _last_error = None
    except Exception as exc:  # noqa: BLE001
        # Broad catch is intentional: this runs unsupervised in a background
        # thread talking to a third-party server outside our control (DNS
        # failure, TLS error, timeout, malformed response, ...). Any failure
        # here must be recorded for the UI, never crash the app.
        _last_error = str(exc)
    finally:
        _refreshing = False


def start_refresh(data_dir: Path) -> bool:
    """Kick off a background refresh. Returns False if one is already running."""
    global _refreshing
    with _lock:
        if _refreshing:
            return False
        _refreshing = True
    threading.Thread(target=_do_refresh, args=(data_dir,), daemon=True).start()
    return True
