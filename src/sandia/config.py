import os
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request


@dataclass
class Settings:
    # data_dir has no default_factory: its default depends on dummy_data,
    # which is itself a field, so it's resolved once in __post_init__ where
    # every field's final value (env var or explicit constructor arg) is
    # already known - that keeps the "dummy mode needs no special access"
    # guarantee consistent regardless of how Settings was constructed.
    data_dir: Path | None = None
    dhcpd_conf_path: Path = field(default_factory=lambda: Path(os.environ.get("DHCPD_CONF_PATH", "/etc/dhcp/dhcpd.conf")))
    leases_path: Path = field(default_factory=lambda: Path(os.environ.get("DHCPD_LEASES_PATH", "/var/lib/dhcp/dhcpd.leases")))
    dhcp_log_path: Path = field(default_factory=lambda: Path(os.environ.get("SANDIA_DHCP_LOG_PATH", "/var/log/syslog")))
    interfaces_conf_path: Path = field(
        default_factory=lambda: Path(os.environ.get("SANDIA_INTERFACES_CONF", "/etc/default/isc-dhcp-server"))
    )
    backup_dir: Path = field(default_factory=lambda: Path(os.environ.get("SANDIA_BACKUP_DIR", "/var/backups/sandia")))
    service_name: str = field(default_factory=lambda: os.environ.get("SANDIA_SERVICE_NAME", "isc-dhcp-server"))
    # None resolves in __post_init__: all interfaces with HTTPS, loopback only with plain HTTP.
    host: str | None = field(default_factory=lambda: os.environ.get("SANDIA_HOST"))
    port: int = field(default_factory=lambda: int(os.environ.get("SANDIA_PORT", "7001")))
    enable_https: bool = field(default_factory=lambda: os.environ.get("SANDIA_HTTPS", "1") != "0")
    dummy_data: bool = field(default_factory=lambda: os.environ.get("SANDIA_DUMMY_DATA", "0") != "0")

    def __post_init__(self) -> None:
        if self.host is None:
            self.host = "0.0.0.0" if self.enable_https else "127.0.0.1"

        if self.data_dir is None:
            if "SANDIA_DATA_DIR" in os.environ:
                self.data_dir = Path(os.environ["SANDIA_DATA_DIR"])
            elif self.dummy_data:
                # Dummy mode promises to need no special access -
                # /var/lib/sandia requires root/a provisioned service
                # account, so fall back to a per-user location that works
                # no matter how dummy_data ended up True (env var, --dummy,
                # or a direct Settings(dummy_data=True) construction).
                self.data_dir = Path.home() / ".local" / "share" / "sandia-dummy"
            else:
                self.data_dir = Path("/var/lib/sandia")

        if self.dummy_data:
            # Testing-only mode: never touch real system paths, regardless
            # of DHCPD_CONF_PATH/DHCPD_LEASES_PATH - always use a sandboxed
            # location under the data dir.
            self.dhcpd_conf_path = self.data_dir / "dummy" / "dhcpd.conf"
            self.leases_path = self.data_dir / "dummy" / "dhcpd.leases"
            self.backup_dir = self.data_dir / "dummy" / "backups"
            self.interfaces_conf_path = self.data_dir / "dummy" / "isc-dhcp-server-defaults"
            self.dhcp_log_path = self.data_dir / "dummy" / "dhcpd.log"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sandia.db"

    @property
    def staging_path(self) -> Path:
        # Deliberately colocated with dhcpd_conf_path (typically /etc/dhcp/),
        # not under data_dir: the isc-dhcp-server AppArmor profile Debian/
        # Ubuntu ship (/etc/apparmor.d/usr.sbin.dhcpd) grants dhcpd read
        # access to /etc/dhcp/** but nothing under /var/lib/sandia/. Staging
        # there made `dhcpd -t` fail with a permission error - enforced by
        # AppArmor's mandatory access control, which root does not bypass -
        # even when Sandia itself runs as root.
        return self.dhcpd_conf_path.parent / ".sandia-staged.conf"

    @property
    def initial_password_path(self) -> Path:
        return self.data_dir / "initial-admin-password"

    @property
    def tls_dir(self) -> Path:
        return self.data_dir / "tls"

    @property
    def session_secret_path(self) -> Path:
        return self.data_dir / "session-secret"


def get_settings(request: Request) -> "Settings":
    return request.app.state.settings
