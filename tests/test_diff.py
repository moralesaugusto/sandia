from sandia.diff import unified_diff_lines


def test_no_changes_returns_empty():
    text = "authoritative;\n"
    assert unified_diff_lines(text, text) == []


def test_added_line_is_flagged():
    lines = unified_diff_lines("authoritative;\n", "authoritative;\ndefault-lease-time 600;\n")
    added = [line for line in lines if line.startswith("+") and not line.startswith("+++")]
    assert any("default-lease-time 600;" in line for line in added)


def test_removed_line_is_flagged():
    lines = unified_diff_lines("authoritative;\ndefault-lease-time 600;\n", "authoritative;\n")
    removed = [line for line in lines if line.startswith("-") and not line.startswith("---")]
    assert any("default-lease-time 600;" in line for line in removed)
