from .config import Settings
from .dhcpd import DhcpdConfig
from .dhcpd.backend import get_backend, live_config_text


def load_live_config(settings: Settings) -> DhcpdConfig:
    """Read the live config (see live_config_text) into the ISC model - for
    Kea, a read-only projection."""
    text = live_config_text(settings)
    return DhcpdConfig() if text is None else get_backend(settings).parse_config(text)
