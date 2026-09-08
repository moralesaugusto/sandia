import time

import pytest

from sandia import oui_cache


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def _reset_global_state():
    oui_cache._refreshing = False
    oui_cache._last_error = None
    oui_cache._memo.clear()
    oui_cache._memo_meta.clear()
    yield
    oui_cache._refreshing = False
    oui_cache._last_error = None
    oui_cache._memo.clear()
    oui_cache._memo_meta.clear()


def test_parse_csv_extracts_and_normalizes_prefix():
    raw = "Registry,Assignment,Organization Name,Organization Address\nMA-L,aabbcc,Some Vendor,Addr\n"
    assert oui_cache._parse_csv(raw) == {"AA:BB:CC": "Some Vendor"}


def test_parse_csv_skips_rows_missing_name_or_malformed_assignment():
    raw = (
        "Registry,Assignment,Organization Name,Organization Address\n"
        "MA-L,AABBCC,,Addr\n"
        "MA-L,AABB,Too Short,Addr\n"
        "MA-L,DDEEFF,Good Vendor,Addr\n"
    )
    assert oui_cache._parse_csv(raw) == {"DD:EE:FF": "Good Vendor"}


def test_status_reports_uncached_when_no_file(tmp_path):
    status = oui_cache.status(tmp_path)
    assert status == oui_cache.CacheStatus(
        cached=False, entry_count=0, fetched_at=None, refreshing=False, last_error=None
    )


def test_do_refresh_downloads_parses_caches_and_writes_file(tmp_path, monkeypatch):
    csv_text = "Registry,Assignment,Organization Name,Organization Address\nMA-L,AABBCC,Test Vendor Inc,Somewhere\n"
    monkeypatch.setattr(oui_cache.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(csv_text.encode()))

    oui_cache._do_refresh(tmp_path)

    status = oui_cache.status(tmp_path)
    assert status.cached is True
    assert status.entry_count == 1
    assert status.last_error is None
    assert status.refreshing is False
    assert (tmp_path / oui_cache.CACHE_FILENAME).exists()
    assert not (tmp_path / (oui_cache.CACHE_FILENAME + ".tmp")).exists()
    assert oui_cache.lookup(tmp_path, "AA:BB:CC") == "Test Vendor Inc"


def test_do_refresh_records_error_on_network_failure(tmp_path, monkeypatch):
    def _raise(*args, **kwargs):
        raise OSError("network unreachable")

    monkeypatch.setattr(oui_cache.urllib.request, "urlopen", _raise)

    oui_cache._do_refresh(tmp_path)

    status = oui_cache.status(tmp_path)
    assert status.cached is False
    assert status.refreshing is False
    assert "network unreachable" in status.last_error


def test_do_refresh_records_error_when_no_entries_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        oui_cache.urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeResponse(b"Registry,Assignment,Organization Name,Organization Address\n"),
    )

    oui_cache._do_refresh(tmp_path)

    status = oui_cache.status(tmp_path)
    assert status.cached is False
    assert "no entries" in status.last_error


def test_start_refresh_returns_false_when_already_running(tmp_path):
    oui_cache._refreshing = True
    assert oui_cache.start_refresh(tmp_path) is False


def test_start_refresh_runs_in_background_and_completes(tmp_path, monkeypatch):
    csv_text = "Registry,Assignment,Organization Name,Organization Address\nMA-L,112233,Async Vendor,Somewhere\n"
    monkeypatch.setattr(oui_cache.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(csv_text.encode()))

    assert oui_cache.start_refresh(tmp_path) is True

    deadline = time.monotonic() + 2
    while oui_cache.status(tmp_path).refreshing and time.monotonic() < deadline:
        time.sleep(0.01)

    status = oui_cache.status(tmp_path)
    assert status.refreshing is False
    assert status.cached is True
    assert status.entry_count == 1
