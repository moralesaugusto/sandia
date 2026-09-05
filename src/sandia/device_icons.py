"""Heuristic device-type icon assignment for reservations - infers a
device category from the hostname and MAC vendor so the Reservations page
shows a relevant icon per row automatically, the way most IPAM/DHCP UIs
badge known device types."""

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
