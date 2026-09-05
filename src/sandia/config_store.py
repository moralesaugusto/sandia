from .config import Settings
from .dhcpd import DhcpdConfig, parse


def load_live_config(settings: Settings) -> DhcpdConfig:
    """Read the live dhcpd.conf, falling back to the last staged draft when
    no live file exists yet (e.g. isc-dhcp-server not installed on this box
    during development)."""
    for path in (settings.dhcpd_conf_path, settings.staging_path):
        if path.exists():
            return parse(path.read_text())
    return DhcpdConfig()
