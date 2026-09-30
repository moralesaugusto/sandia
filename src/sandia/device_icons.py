"""Heuristic device-type icon assignment for reservations - infers a
device category from the hostname and MAC vendor so the Reservations page
shows a relevant icon per row automatically, the way most IPAM/DHCP UIs
badge known device types."""

from .i18n import N_
from .vendors import lookup_vendor

_HOSTNAME_HINTS: list[tuple[str, str]] = [
    ("printer", "device-printer"),
    ("print", "device-printer"),
    ("phone", "device-phone"),
    ("iphone", "device-phone"),
    ("android", "device-phone"),
    ("pixel", "device-phone"),
    ("tablet", "device-phone"),
    ("ipad", "device-phone"),
    ("tv", "device-tv"),
    ("roku", "device-tv"),
    ("chromecast", "device-tv"),
    ("appletv", "device-tv"),
    ("cam", "device-camera"),
    ("camera", "device-camera"),
    ("doorbell", "device-camera"),
    ("nas", "device-server"),
    ("storage", "device-server"),
    ("server", "device-server"),
    ("sensor", "device-iot"),
    ("iot", "device-iot"),
    ("esp", "device-iot"),
    ("switch", "device-network"),
    ("router", "device-network"),
    ("gateway", "device-network"),
    ("accesspoint", "device-network"),
    ("laptop", "device-laptop"),
    ("macbook", "device-laptop"),
    ("workstation", "device-laptop"),
    ("desktop", "device-laptop"),
    ("pc", "device-laptop"),
]

_VENDOR_HINTS: list[tuple[str, str]] = [
    ("Raspberry Pi", "device-iot"),
    ("Espressif", "device-iot"),
    ("Sonos", "device-tv"),
    ("Roku", "device-tv"),
    ("Nintendo", "device-game"),
    ("PlayStation", "device-game"),
    ("Ubiquiti", "device-network"),
    ("TP-Link", "device-network"),
    ("Netgear", "device-network"),
    ("Cisco", "device-network"),
    ("Dell", "device-laptop"),
    ("Lenovo", "device-laptop"),
    ("HP", "device-laptop"),
    ("Intel", "device-laptop"),
    ("Apple", "device-phone"),
    ("Samsung", "device-phone"),
    ("Amazon", "device-iot"),
]


def device_icon_for(name: str, mac: str | None) -> str:
    lowered = name.lower()
    for hint, icon_name in _HOSTNAME_HINTS:
        if hint in lowered:
            return icon_name

    vendor = lookup_vendor(mac) or ""
    for hint, icon_name in _VENDOR_HINTS:
        if hint in vendor:
            return icon_name

    return "device-generic"


DEVICE_LABELS: dict[str, str] = {
    "device-printer": N_("Printer"),
    "device-phone": N_("Phone / tablet"),
    "device-laptop": N_("Computer"),
    "device-tv": N_("TV / media player"),
    "device-camera": N_("Camera"),
    "device-server": N_("Server / NAS"),
    "device-iot": N_("IoT device"),
    "device-network": N_("Network equipment"),
    "device-game": N_("Game console"),
    "device-generic": N_("Unknown device"),
}

# Hostname/vendor -> best-effort OS guess. There's no real client
# fingerprinting here (that would need the DHCP options a client actually
# sent, which the lease file doesn't record) - this is the same class of
# heuristic as the device icon, just for OS, and is always shown as a
# guess in the UI rather than a fact.
_HOSTNAME_OS_HINTS: list[tuple[str, str]] = [
    ("iphone", "iOS"),
    ("ipad", "iPadOS"),
    ("macbook", "macOS"),
    ("imac", "macOS"),
    ("android", "Android"),
    ("pixel", "Android"),
]

_VENDOR_OS_HINTS: list[tuple[str, str]] = [
    ("Raspberry Pi", N_("Linux (likely Raspberry Pi OS)")),
    ("Espressif", N_("Embedded firmware (ESP8266/ESP32)")),
    ("Apple", "iOS/macOS"),
    ("Samsung", "Android"),
    ("Sonos", N_("Embedded firmware")),
    ("Roku", N_("Embedded firmware")),
    ("Nintendo", N_("Console firmware")),
    ("PlayStation", N_("Console firmware")),
    ("Ubiquiti", N_("Network device firmware")),
    ("TP-Link", N_("Network device firmware")),
    ("Netgear", N_("Network device firmware")),
    ("Cisco", N_("Network device firmware")),
    ("Dell", N_("Windows or Linux (likely)")),
    ("Lenovo", N_("Windows or Linux (likely)")),
    ("HP", N_("Windows or Linux (likely)")),
    ("Microsoft", "Windows"),
]


def guess_os(name: str, mac: str | None) -> str | None:
    lowered = name.lower()
    for hint, os_name in _HOSTNAME_OS_HINTS:
        if hint in lowered:
            return os_name

    vendor = lookup_vendor(mac) or ""
    for hint, os_name in _VENDOR_OS_HINTS:
        if hint in vendor:
            return os_name

    return None
