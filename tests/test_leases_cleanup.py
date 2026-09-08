from sandia.leases_cleanup import clean_leases_text


def test_no_duplicates_returns_text_unchanged():
    text = "lease 10.0.0.1 {\n  binding state active;\n}\n"
    cleaned, removed = clean_leases_text(text)
    assert cleaned == text
    assert removed == 0


def test_keeps_only_last_block_per_ip():
    text = (
        "lease 10.0.0.1 {\n  binding state free;\n}\n"
        "lease 10.0.0.1 {\n  binding state active;\n}\n"
    )
    cleaned, removed = clean_leases_text(text)
    assert removed == 1
    assert cleaned.count("lease 10.0.0.1") == 1
    assert "binding state active;" in cleaned
    assert "binding state free;" not in cleaned


def test_preserves_unrelated_content_verbatim():
    text = (
        "# The format of this file is documented in the dhcpd.leases(5) manual page.\n"
        "server-duid \"some-opaque-value\";\n\n"
        "lease 10.0.0.1 {\n  binding state free;\n}\n"
        "lease 10.0.0.1 {\n  binding state active;\n}\n"
        "lease 10.0.0.2 {\n  binding state active;\n}\n"
    )
    cleaned, removed = clean_leases_text(text)
    assert removed == 1
    assert "# The format of this file" in cleaned
    assert 'server-duid "some-opaque-value";' in cleaned
    assert "lease 10.0.0.2" in cleaned


def test_multiple_ips_each_deduplicated_independently():
    text = (
        "lease 10.0.0.1 {\n  binding state free;\n}\n"
        "lease 10.0.0.2 {\n  binding state free;\n}\n"
        "lease 10.0.0.1 {\n  binding state active;\n}\n"
        "lease 10.0.0.2 {\n  binding state active;\n}\n"
    )
    cleaned, removed = clean_leases_text(text)
    assert removed == 2
    assert cleaned.count("lease 10.0.0.1") == 1
    assert cleaned.count("lease 10.0.0.2") == 1


def test_empty_file_is_a_no_op():
    cleaned, removed = clean_leases_text("")
    assert cleaned == ""
    assert removed == 0
