import datetime
import ipaddress
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def ensure_self_signed_cert(tls_dir: Path) -> tuple[Path, Path]:
    tls_dir.mkdir(parents=True, exist_ok=True)
    cert_path = tls_dir / "cert.pem"
    key_path = tls_dir / "key.pem"

    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    hostname = socket.gethostname()
    key = ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.datetime.now(datetime.UTC)
    san_names: list[x509.GeneralName] = [x509.DNSName(hostname), x509.DNSName("localhost")]
    try:
        san_names.append(x509.IPAddress(ipaddress.ip_address(socket.gethostbyname(hostname))))
    except (socket.gaierror, ValueError):
        pass
    san_names.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    return cert_path, key_path
