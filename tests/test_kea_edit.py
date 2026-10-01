import copy
import json

from sandia.dhcpd.kea import to_plain_json
from sandia.dhcpd.kea_edit import patch_json

TEXT = """\
# header comment
{
    "a": 1, // trailing comment
    "list": [
        { "id": 1, "x": "one" },  # first
        { "id": 2, "x": "two" },
        { "id": 3, "x": "three" }
    ],
    "inline": [ "eth0" ],
    "empty": [ ]
}
"""


def _patched(change):
    old = json.loads(to_plain_json(TEXT))
    new = copy.deepcopy(old)
    change(new)
    text = patch_json(TEXT, old, new)
    assert json.loads(to_plain_json(text)) == new
    return text


def test_unchanged_value_returns_identical_text():
    assert _patched(lambda new: None) == TEXT


def test_scalar_change_keeps_every_comment():
    text = _patched(lambda new: new.update(a=2))
    assert '"a": 2, // trailing comment' in text and "# header comment" in text and "# first" in text


def test_deleting_the_last_element_leaves_no_trailing_comma():
    text = _patched(lambda new: new["list"].pop())
    assert '{ "id": 2, "x": "two" }\n' in text and "three" not in text


def test_deleting_a_middle_element_keeps_its_neighbours_verbatim():
    text = _patched(lambda new: new["list"].pop(1))
    assert '{ "id": 1, "x": "one" },  # first\n        { "id": 3, "x": "three" }' in text


def test_editing_an_element_patches_it_in_place():
    text = _patched(lambda new: new["list"][0].update(x="uno"))
    assert '{ "id": 1, "x": "uno" },  # first' in text


def test_appending_follows_container_layout():
    text = _patched(lambda new: (new["inline"].append("eth1"), new["list"].append({"id": 4})))
    assert '"inline": [ "eth0", "eth1" ]' in text
    assert '{ "id": 3, "x": "three" },\n        {\n            "id": 4\n        }' in text


def test_filling_an_empty_container_and_adding_members():
    text = _patched(lambda new: (new["empty"].append("x"), new.update(b={"c": True})))
    assert '"b": {' in text


def test_replacing_every_element_rewrites_the_container():
    _patched(lambda new: new.update(list=[{"id": 9}]))
