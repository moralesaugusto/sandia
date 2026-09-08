from sandia.device_icons import DEVICE_LABELS, device_icon_for, guess_os


def test_hostname_hint_takes_priority():
    assert device_icon_for("office-printer", "00:11:22:33:44:55") == "device-printer"
    assert device_icon_for("kitchen-tv", None) == "device-tv"
    assert device_icon_for("johns-laptop", None) == "device-laptop"


def test_vendor_hint_used_when_no_hostname_match():
    assert device_icon_for("device1", "b8:27:eb:12:34:56") == "device-iot"  # Raspberry Pi
    assert device_icon_for("device2", "ac:de:48:11:22:33") == "device-phone"  # Apple


def test_falls_back_to_generic():
    assert device_icon_for("mystery-box", "ff:ff:ff:ff:ff:ff") == "device-generic"
    assert device_icon_for("mystery-box", None) == "device-generic"


def test_every_icon_has_a_label():
    for icon_name in {device_icon_for("x", None), device_icon_for("printer", None)}:
        assert icon_name in DEVICE_LABELS


def test_guess_os_hostname_hint():
    assert guess_os("johns-iphone", None) == "iOS"
    assert guess_os("kitchen-android-tablet", None) == "Android"


def test_guess_os_vendor_hint():
    assert guess_os("device1", "b8:27:eb:12:34:56") == "Linux (likely Raspberry Pi OS)"


def test_guess_os_unknown_returns_none():
    assert guess_os("mystery-box", "ff:ff:ff:ff:ff:ff") is None
    assert guess_os("mystery-box", None) is None
