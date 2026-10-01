"""The post-apply rollback window: for a few minutes after a change is
applied, every page offers to keep it or roll it back to the backup taken
just before it. Nothing reverts on its own - the record is only an offer.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from .config import Settings
from .dhcpd.backend import live_config_sha

ROLLBACK_WINDOW = 600


@dataclass
class LastApply:
    backup: str
    applied_at: float
    username: str
    action: str
    installed_sha: str

    @property
    def minutes_left(self) -> int:
        return max(1, round((self.applied_at + ROLLBACK_WINDOW - time.time()) / 60))


def _last_apply_path(settings: Settings):
    return settings.data_dir / "last-apply.json"


def record_apply(settings: Settings, backup: str, username: str, action: str) -> None:
    record = LastApply(backup=backup, applied_at=time.time(), username=username, action=action, installed_sha=live_config_sha(settings))
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _last_apply_path(settings).write_text(json.dumps(asdict(record)))


def clear_apply(settings: Settings) -> None:
    _last_apply_path(settings).unlink(missing_ok=True)


def rollback_offer(settings: Settings) -> LastApply | None:
    """The last apply, while it can still be rolled back from the banner:
    within the window, and the live config is still what it installed (a
    later change or a manual edit ends the offer)."""
    path = _last_apply_path(settings)
    if not path.is_file():
        return None
    record = LastApply(**json.loads(path.read_text()))
    if record.applied_at < time.time() - ROLLBACK_WINDOW or record.installed_sha != live_config_sha(settings):
        return None
    if not (settings.backup_dir / record.backup).is_file():
        return None
    return record
