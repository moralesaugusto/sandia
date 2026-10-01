from __future__ import annotations

import asyncio
import os
import shutil
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


async def _run(*args: str) -> CommandResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        return CommandResult(ok=False, stdout="", stderr=str(exc), command_missing=True)
    stdout, stderr = await proc.communicate()
    return CommandResult(ok=proc.returncode == 0, stdout=stdout.decode(), stderr=stderr.decode())


async def stage(settings: Settings, new_text: str) -> None:
    settings.staging_path.parent.mkdir(parents=True, exist_ok=True)
    settings.staging_path.write_text(new_text)


async def check_config(settings: Settings) -> CommandResult:
    backend = get_backend(settings)
    if settings.dummy_data:
        return CommandResult(ok=True, stdout=f"dummy mode: skipping {backend.validator} -t", stderr="")
    return await _run(*backend.check_args(settings.staging_path))


async def check_live_config(settings: Settings) -> CommandResult:
    """Validate the config file actually on disk, read-only - unlike
    check_config(), this never touches the staging file, so it's safe to
    call from diagnostics without disturbing an in-progress raw-config
    edit the user may have staged but not applied yet."""
    backend = get_backend(settings)
    if settings.dummy_data:
        return CommandResult(ok=True, stdout=f"dummy mode: skipping {backend.validator} -t", stderr="")
    if not settings.dhcpd_conf_path.exists():
        return CommandResult(ok=False, stdout="", stderr=f"{settings.dhcpd_conf_path} does not exist")
    return await _run(*backend.check_args(settings.dhcpd_conf_path))


def _replace_atomically(source: Path, target: Path) -> None:
    # Copy next to the target, then rename over it: a crash mid-copy leaves
    # the live config intact instead of truncated.
    tmp = target.with_name(target.name + ".sandia-tmp")
    shutil.copyfile(source, tmp)
    if target.exists():
        shutil.copymode(target, tmp)
    os.replace(tmp, target)


async def install_config(settings: Settings) -> tuple[CommandResult, Path | None]:
    """Back up the live config, then atomically install the staged one.
    Returns the result and the backup path (None if there was no previous
    config to back up). Runs whether or not dummy mode is on - dummy mode's
    paths are already sandboxed by Settings, so this is plain file I/O
    against a real path either way. If the target isn't writable (not
    running as root/sudo), this fails cleanly instead of raising."""
    backup = None
    try:
        settings.backup_dir.mkdir(parents=True, exist_ok=True)
        if settings.dhcpd_conf_path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")
            backup = settings.backup_dir / f"{get_backend(settings).backup_prefix}.{stamp}"
            shutil.copyfile(settings.dhcpd_conf_path, backup)
        settings.dhcpd_conf_path.parent.mkdir(parents=True, exist_ok=True)
        _replace_atomically(settings.staging_path, settings.dhcpd_conf_path)
    except OSError as exc:
        return CommandResult(ok=False, stdout="", stderr=str(exc)), backup
    return CommandResult(ok=True, stdout="installed", stderr=""), backup


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
    restarted on it."""
    await stage(settings, new_text)

    checked = await check_config(settings)
    if not checked.ok:
        return ApplyResult(ok=False, stage="check", output=checked.stderr or checked.stdout)

    installed, backup = await install_config(settings)
    if not installed.ok:
        return ApplyResult(ok=False, stage="apply", output=installed.stderr or installed.stdout)

    reloaded = _can_reload(settings)
    failure = await _restart_and_verify(settings)
    if failure is None:
        action = "reloaded its configuration" if reloaded else "restarted"
        return ApplyResult(ok=True, stage="", output=f"installed; {settings.service_name} {action}")

    if backup is None:
        return ApplyResult(
            ok=False,
            stage="restart",
            output=f"{failure}\nThere was no previous config to roll back to; the new config is still installed.",
        )
    try:
        _replace_atomically(backup, settings.dhcpd_conf_path)
    except OSError as exc:
        return ApplyResult(ok=False, stage="restart", output=f"{failure}\nRollback failed: {exc}")
    rollback_failure = await _restart_and_verify(settings)
    if rollback_failure is None:
        rollback = f"Rolled back to the previous config ({backup.name}); {settings.service_name} is running again."
    else:
        rollback = f"Rolled back to the previous config ({backup.name}), but the service still failed: {rollback_failure}"
    return ApplyResult(ok=False, stage="restart", output=f"{failure}\n{rollback}")


async def apply_config(settings: Settings, config: DhcpdConfig) -> ApplyResult:
    """Apply an edited config model: render it in the backend's own format
    (dhcpd.conf, or a minimal patch of kea-dhcp4.conf), then run the same
    validate/install/verify pipeline as a raw edit."""
    try:
        text = get_backend(settings).render_config(live_config_text(settings) or "", config)
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
