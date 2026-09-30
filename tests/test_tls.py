from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec

from sandia.tls import ensure_self_signed_cert


def test_creates_cert_and_key_when_missing(tmp_path):
    tls_dir = tmp_path / "tls"
    cert_path, key_path = ensure_self_signed_cert(tls_dir)

    assert cert_path.exists()
    assert key_path.exists()
    assert oct(key_path.stat().st_mode)[-3:] == "600"


def test_certificate_uses_elliptic_curve(tmp_path):
    cert_path, _ = ensure_self_signed_cert(tmp_path / "tls")
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    assert isinstance(cert.public_key().curve, ec.SECP256R1)


def test_does_not_regenerate_existing_cert(tmp_path):
    tls_dir = tmp_path / "tls"
    cert_path, key_path = ensure_self_signed_cert(tls_dir)
    original_cert = cert_path.read_bytes()
    original_key = key_path.read_bytes()

    cert_path2, key_path2 = ensure_self_signed_cert(tls_dir)

    assert cert_path2 == cert_path
    assert key_path2 == key_path
    assert cert_path.read_bytes() == original_cert
    assert key_path.read_bytes() == original_key


def test_regenerates_if_only_one_file_present(tmp_path):
    tls_dir = tmp_path / "tls"
    _cert_path, key_path = ensure_self_signed_cert(tls_dir)
    original_key = key_path.read_bytes()
    key_path.unlink()

    ensure_self_signed_cert(tls_dir)

    assert key_path.exists()
    assert key_path.read_bytes() != original_key  # regenerated as a matching pair
