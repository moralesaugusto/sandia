from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import Settings
from .ast import DhcpdConfig
from .backend import get_backend, live_config_text
from .kea_ctrl import KeaControlError, send_command
from .parser import ParseError


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    # True only when the command itself couldn't be found/executed (e.g.
    # `dhcpd` not installed) - distinct from the command running and
    # reporting a real failure. Diagnostics needs this distinction to avoid
    # claiming "config is invalid" when it actually just couldn't check.
    command_missing: bool = False


@dataclass
class ApplyResult:
    ok: bool
    stage: str  # "check" or "apply" when failed, "" on success
    output: str
    # The pre-change backup, on success - what the rollback banner restores.
    backup: Path | None = None


async def _run(*args: str) -> CommandResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        return CommandResult(ok=False, stdout="", stderr=str(exc), command_missing=True)
    stdout, stderr = await proc.communicate()
    return CommandResult(ok=proc.returncode == 0, stdout=stdout.decode(), stderr=stderr.decode())


# SEC-2026-02 (fixed): apply, restore and rollback each read the live
# config, install a new one and record what they did. Interleaved, two of
# them could validate one file and install another or record the wrong
# rollback target, so the routes hold this lock for the whole operation.
# Sandia runs as a single uvicorn process, so an in-process lock is enough.
config_lock = asyncio.Lock()


def _check_dir(settings: Settings, directory: Path) -> None:
    """Refuse to write the DHCP config or its backups into a directory
    another local account could swap files in - such an account could
    replace a validated file before it is installed (SEC-2026-02). Dummy
    mode's paths are a per-user sandbox, so it is exempt."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o755)
    if settings.dummy_data:
        return
    st = directory.stat()
    if st.st_uid not in (0, os.geteuid()) or st.st_mode & 0o022:
        raise OSError(f"refusing to write in {directory}: it must be owned by root or the Sandia user and not writable by group or others")


@contextmanager
def _staged(settings: Settings, text: str) -> Iterator[Path]:
    """A private staging file next to the live config (see
    Settings.staging_dir), deleted afterwards. Each operation gets its own
    exclusively created file with a random name, so concurrent requests
    never share one and nothing can be planted at a predictable path
    (SEC-2026-02, fixed)."""
    directory = settings.staging_dir
    _check_dir(settings, directory)
    fd, name = tempfile.mkstemp(prefix=".sandia-staged-", suffix=".conf", dir=directory)
    path = Path(name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        yield path
    finally:
        path.unlink(missing_ok=True)


async def _check(settings: Settings, path: Path) -> CommandResult:
    backend = get_backend(settings)
    if settings.dummy_data:
        return CommandResult(ok=True, stdout=f"dummy mode: skipping {backend.validator} -t", stderr="")
    return await _run(*backend.check_args(path))


async def validate_text(settings: Settings, text: str) -> CommandResult:
    """Validate a proposed config without installing it."""
    try:
        with _staged(settings, text) as path:
            return await _check(settings, path)
    except OSError as exc:
        return CommandResult(ok=False, stdout="", stderr=str(exc))


async def check_live_config(settings: Settings) -> CommandResult:
    """Validate the config file actually on disk, read-only."""
    if not settings.dummy_data and not settings.dhcpd_conf_path.exists():
        return CommandResult(ok=False, stdout="", stderr=f"{settings.dhcpd_conf_path} does not exist")
    return await _check(settings, settings.dhcpd_conf_path)


def _install(staged: Path, target: Path) -> None:
    # Rename the validated file itself over the target: what was checked is
    # exactly what gets installed (SEC-2026-02), and a crash mid-way leaves
    # the live config intact instead of truncated.
    staged.chmod(target.stat().st_mode & 0o7777 if target.exists() else 0o644)
    os.replace(staged, target)


def _backup(settings: Settings) -> Path | None:
    """Copy the live config into a new backup file (None if there is no live
    config). "x" mode creates the file exclusively and never follows a
    symlink planted at its name."""
    if not settings.dhcpd_conf_path.exists():
        return None
    _check_dir(settings, settings.backup_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")
    backup = settings.backup_dir / f"{get_backend(settings).backup_prefix}.{stamp}"
    with settings.dhcpd_conf_path.open("rb") as src, backup.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    return backup


def _can_reload(settings: Settings) -> bool:
    return get_backend(settings).name == "kea" and not settings.dummy_data and settings.kea_control_socket.exists()


async def _reload_kea(settings: Settings) -> CommandResult:
    """config-reload: Kea re-reads its config file without a restart. If the
    new config is rejected Kea keeps serving with the old one."""
    try:
        response = await send_command(settings.kea_control_socket, "config-reload")
    except KeaControlError as exc:
        return CommandResult(ok=False, stdout="", stderr=str(exc))
    text = str(response.get("text", ""))
    if response.get("result") == 0:
        return CommandResult(ok=True, stdout=text, stderr="")
    return CommandResult(ok=False, stdout="", stderr=text or f"config-reload failed (result {response.get('result')})")


async def _restart_and_verify(settings: Settings) -> str | None:
    """Make the service load the installed config - config-reload over the
    Kea control socket when one is configured, else a restart - and confirm
    it's running. Returns None on success, otherwise the reason it failed."""
    restarted = await (_reload_kea(settings) if _can_reload(settings) else restart_service(settings))
    if not restarted.ok:
        return (restarted.stderr or restarted.stdout).strip() or "systemctl restart failed"
    status = await service_status(settings)
    if status != "active":
        return f"{settings.service_name} is '{status}' after restart"
    return None


async def apply_new_config(settings: Settings, new_text: str) -> ApplyResult:
    """Stage -> validate -> install -> restart -> verify. The live config is
    only ever touched after validation succeeds; if the service doesn't come
    back up on the new config, the previous one is restored and the service
    restarted on it. Callers hold config_lock."""
    try:
        with _staged(settings, new_text) as staged:
            checked = await _check(settings, staged)
            if not checked.ok:
                return ApplyResult(ok=False, stage="check", output=checked.stderr or checked.stdout)
            backup = _backup(settings)
            _install(staged, settings.dhcpd_conf_path)
    except OSError as exc:
        return ApplyResult(ok=False, stage="apply", output=str(exc))

    reloaded = _can_reload(settings)
    failure = await _restart_and_verify(settings)
    if failure is None:
        action = "reloaded its configuration" if reloaded else "restarted"
        return ApplyResult(ok=True, stage="", output=f"installed; {settings.service_name} {action}", backup=backup)

    if backup is None:
        return ApplyResult(
            ok=False,
            stage="restart",
            output=f"{failure}\nThere was no previous config to roll back to; the new config is still installed.",
        )
    try:
        with _staged(settings, backup.read_text()) as staged:
            _install(staged, settings.dhcpd_conf_path)
    except OSError as exc:
        return ApplyResult(ok=False, stage="restart", output=f"{failure}\nRollback failed: {exc}")
    rollback_failure = await _restart_and_verify(settings)
    if rollback_failure is None:
        rollback = f"Rolled back to the previous config ({backup.name}); {settings.service_name} is running again."
    else:
        rollback = f"Rolled back to the previous config ({backup.name}), but the service still failed: {rollback_failure}"
    return ApplyResult(ok=False, stage="restart", output=f"{failure}\n{rollback}")


def render_config_text(settings: Settings, config: DhcpdConfig) -> str:
    """An edited config model in the backend's own format (dhcpd.conf, or a
    minimal patch of kea-dhcp4.conf). Raises ParseError/ValueError when the
    edit can't be written."""
    return get_backend(settings).render_config(live_config_text(settings) or "", config)


async def apply_config(settings: Settings, config: DhcpdConfig) -> ApplyResult:
    """Render an edited config model, then run the same validate/install/
    verify pipeline as a raw edit."""
    try:
        text = render_config_text(settings, config)
    except (ParseError, ValueError) as exc:
        return ApplyResult(ok=False, stage="check", output=str(exc))
    return await apply_new_config(settings, text)


async def restart_service(settings: Settings) -> CommandResult:
    if settings.dummy_data:
        return CommandResult(ok=True, stdout="dummy mode: service restarted (simulated)", stderr="")
    return await _run("systemctl", "restart", settings.service_name)


async def enable_service(settings: Settings) -> CommandResult:
    if settings.dummy_data:
        return CommandResult(ok=True, stdout="dummy mode: service enabled (simulated)", stderr="")
    return await _run("systemctl", "enable", settings.service_name)


async def disable_service(settings: Settings) -> CommandResult:
    if settings.dummy_data:
        return CommandResult(ok=True, stdout="dummy mode: service disabled (simulated)", stderr="")
    return await _run("systemctl", "disable", settings.service_name)


async def service_status(settings: Settings) -> str:
    if settings.dummy_data:
        return "active"
    result = await _run("systemctl", "is-active", settings.service_name)
    return result.stdout.strip() or "unknown"


async def service_is_enabled(settings: Settings) -> bool:
    if settings.dummy_data:
        return True
    result = await _run("systemctl", "is-enabled", settings.service_name)
    return result.ok
