import json

from sandia import vendors
from sandia.vendors import lookup_vendor


def test_known_prefix_matches_case_insensitively():
    assert lookup_vendor("b8:27:eb:11:22:33") == "Raspberry Pi Foundation"
    assert lookup_vendor("B8:27:EB:11:22:33") == "Raspberry Pi Foundation"


def test_unknown_prefix_returns_none():
    assert lookup_vendor("ff:ff:ff:ff:ff:ff") is None


def test_none_and_malformed_input_returns_none():
    assert lookup_vendor(None) is None
    assert lookup_vendor("not-a-mac") is None


def test_falls_back_to_cached_oui_entry_when_not_in_builtin_list(tmp_path, monkeypatch):
    cache_file = tmp_path / "oui_cache.json"
    cache_file.write_text(json.dumps({"fetched_at": "2026-01-01T00:00:00+00:00", "entries": {"AA:BB:CC": "Totally New Vendor"}}))
    monkeypatch.setattr(vendors, "_data_dir", tmp_path)

    assert lookup_vendor("aa:bb:cc:11:22:33") == "Totally New Vendor"


def test_builtin_list_takes_priority_over_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "oui_cache.json"
    cache_file.write_text(json.dumps({"fetched_at": "2026-01-01T00:00:00+00:00", "entries": {"B8:27:EB": "Wrong Name"}}))
    monkeypatch.setattr(vendors, "_data_dir", tmp_path)

    assert lookup_vendor("b8:27:eb:11:22:33") == "Raspberry Pi Foundation"


def test_no_data_dir_configured_returns_none_for_unknown_prefix(monkeypatch):
    monkeypatch.setattr(vendors, "_data_dir", None)
    assert lookup_vendor("ff:ff:ff:ff:ff:ff") is None
