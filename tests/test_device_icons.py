from sandia.device_icons import device_icon_for


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
