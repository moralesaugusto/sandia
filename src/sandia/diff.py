import difflib


def unified_diff_lines(old_text: str, new_text: str, filename: str = "dhcpd.conf") -> list[str]:
    return list(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"current/{filename}",
            tofile=f"staged/{filename}",
            lineterm="",
        )
    )
