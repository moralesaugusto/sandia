"""OUI (MAC address prefix) to vendor-name lookup.

Ships with a small built-in list of common vendors that works with zero
setup, fully offline. If a local cache of the full IEEE OUI registry has
been downloaded (see `oui_cache.py` and the "Update OUI database" button
on the About page), it's consulted as a fallback for anything the built-in
list doesn't recognize.
"""

from __future__ import annotations

from pathlib import Path

from . import oui_cache

_data_dir: Path | None = None


def configure(data_dir: Path) -> None:
    """Point vendor lookups at the app's data directory, so a downloaded
    OUI cache (if any) can be found. Called once from create_app()."""
    global _data_dir
    _data_dir = data_dir


_OUI_PREFIXES: dict[str, str] = {
    "00:1A:11": "Google",
    "3C:5A:B4": "Google",
    "F4:F5:D8": "Google",
    "A4:77:33": "Google",
    "00:17:88": "Philips",
    "B8:27:EB": "Raspberry Pi Foundation",
    "DC:A6:32": "Raspberry Pi Foundation",
    "E4:5F:01": "Raspberry Pi Foundation",
    "00:0C:29": "VMware",
    "00:50:56": "VMware",
    "08:00:27": "VirtualBox",
    "52:54:00": "QEMU/KVM",
    "00:1C:42": "Parallels",
    "AC:DE:48": "Apple",
    "F0:18:98": "Apple",
    "3C:15:C2": "Apple",
    "A4:5E:60": "Apple",
    "DC:A9:04": "Apple",
    "88:66:A5": "Apple",
    "00:1B:63": "Apple",
    "28:CF:E9": "Apple",
    "F4:0F:24": "Apple",
    "00:16:CB": "Apple",
    "3C:07:54": "Apple",
    "AC:BC:32": "Apple",
    "00:03:93": "Apple",
    "F0:D1:A9": "Apple",
    "00:1E:C2": "Apple",
    "18:65:71": "Samsung",
    "8C:71:F8": "Samsung",
    "00:12:FB": "Samsung",
    "5C:0A:5B": "Samsung",
    "E8:50:8B": "Samsung",
    "00:26:37": "Samsung",
    "00:0D:3A": "Microsoft",
    "00:03:FF": "Microsoft",
    "00:50:F2": "Microsoft",
    "00:15:5D": "Microsoft (Hyper-V)",
    "00:1D:D8": "Microsoft",
    "B0:35:9F": "Dell",
    "D4:BE:D9": "Dell",
    "F8:BC:12": "Dell",
    "18:03:73": "Dell",
    "A4:BA:DB": "Dell",
    "F0:1F:AF": "HP",
    "3C:D9:2B": "HP",
    "9C:8E:99": "HP",
    "70:5A:0F": "HP",
    "00:1F:29": "HP",
    "00:1E:65": "Lenovo",
    "54:EE:75": "Lenovo",
    "E4:54:E8": "Lenovo",
    "00:26:B0": "Lenovo",
    "00:E0:4C": "Realtek",
    "52:54:00:12": "Realtek",
    "00:23:24": "Netgear",
    "A0:04:60": "Netgear",
    "20:E5:2A": "Netgear",
    "84:1B:5E": "Netgear",
    "94:10:3E": "TP-Link",
    "50:C7:BF": "TP-Link",
    "EC:08:6B": "TP-Link",
    "F4:F2:6D": "TP-Link",
    "A0:F3:C1": "TP-Link",
    "00:1D:0F": "TP-Link",
    "B0:4E:26": "Ubiquiti",
    "24:A4:3C": "Ubiquiti",
    "78:8A:20": "Ubiquiti",
    "FC:EC:DA": "Ubiquiti",
    "DC:9F:DB": "Ubiquiti",
    "E0:63:DA": "Amazon",
    "44:65:0D": "Amazon",
    "F0:81:73": "Amazon",
    "68:37:E9": "Amazon",
    "AC:63:BE": "Amazon",
    "18:74:2E": "Amazon (Ring)",
    "B4:75:0E": "Sonos",
    "5C:AA:FD": "Sonos",
    "94:9F:3E": "Sonos",
    "00:1C:B3": "Sonos",
    "3C:6A:2C": "Google (Nest)",
    "64:16:66": "Google (Nest)",
    "18:B4:30": "Google (Nest)",
    "70:88:6B": "Roku",
    "B8:A1:75": "Roku",
    "DC:3A:5E": "Roku",
    "AC:3F:A4": "Roku",
    "40:B4:CD": "Espressif (ESP8266/ESP32)",
    "24:0A:C4": "Espressif (ESP8266/ESP32)",
    "3C:71:BF": "Espressif (ESP8266/ESP32)",
    "84:CC:A8": "Espressif (ESP8266/ESP32)",
    "EC:FA:BC": "Espressif (ESP8266/ESP32)",
    "00:0E:8F": "Cisco",
    "00:1B:D4": "Cisco",
    "00:26:99": "Cisco",
    "70:69:5A": "Cisco",
    "3C:CE:73": "Cisco",
    "9C:57:AD": "Sony",
    "00:24:BE": "Sony",
    "AC:9B:0A": "Sony (PlayStation)",
    "00:1F:A7": "Sony (PlayStation)",
    "7C:BB:8A": "Nintendo",
    "00:09:BF": "Nintendo",
    "98:B6:E9": "Nintendo",
    "00:1E:35": "Intel",
    "00:15:17": "Intel",
    "3C:97:0E": "Intel",
    "A0:36:9F": "Intel",
}


def lookup_vendor(mac: str | None) -> str | None:
    if not mac:
        return None
    normalized = mac.upper().replace("-", ":")
    parts = normalized.split(":")
    if len(parts) < 4:
        return None
    prefix4 = ":".join(parts[:4])
    if prefix4 in _OUI_PREFIXES:
        return _OUI_PREFIXES[prefix4]
    prefix3 = ":".join(parts[:3])
    if prefix3 in _OUI_PREFIXES:
        return _OUI_PREFIXES[prefix3]

    if _data_dir is not None:
        return oui_cache.lookup(_data_dir, prefix3)
    return None
