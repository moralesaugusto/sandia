from sandia.vendors import lookup_vendor


def test_known_prefix_matches_case_insensitively():
    assert lookup_vendor("b8:27:eb:11:22:33") == "Raspberry Pi Foundation"
    assert lookup_vendor("B8:27:EB:11:22:33") == "Raspberry Pi Foundation"


def test_unknown_prefix_returns_none():
    assert lookup_vendor("ff:ff:ff:ff:ff:ff") is None


def test_none_and_malformed_input_returns_none():
    assert lookup_vendor(None) is None
    assert lookup_vendor("not-a-mac") is None
