from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import datetime

from ..config import Settings


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
    if settings.dummy_data:
        return CommandResult(ok=True, stdout="dummy mode: skipping dhcpd -t", stderr="")
    return await _run("dhcpd", "-t", "-cf", str(settings.staging_path))


async def check_live_config(settings: Settings) -> CommandResult:
    """Validate the config file actually on disk, read-only - unlike
    check_config(), this never touches the staging file, so it's safe to
    call from diagnostics without disturbing an in-progress raw-config
    edit the user may have staged but not applied yet."""
    if settings.dummy_data:
        return CommandResult(ok=True, stdout="dummy mode: skipping dhcpd -t", stderr="")
    if not settings.dhcpd_conf_path.exists():
        return CommandResult(ok=False, stdout="", stderr=f"{settings.dhcpd_conf_path} does not exist")
    return await _run("dhcpd", "-t", "-cf", str(settings.dhcpd_conf_path))


async def install_config(settings: Settings) -> CommandResult:
    """Back up the live config, then install the staged one. Runs whether
    or not dummy mode is on - dummy mode's paths are already sandboxed by
    Settings, so this is plain file I/O against a real path either way. If
    the target isn't writable (not running as root/sudo), this fails
    cleanly instead of raising."""
    try:
        settings.backup_dir.mkdir(parents=True, exist_ok=True)
        if settings.dhcpd_conf_path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")
            shutil.copyfile(settings.dhcpd_conf_path, settings.backup_dir / f"dhcpd.conf.{stamp}")
        settings.dhcpd_conf_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(settings.staging_path, settings.dhcpd_conf_path)
    except OSError as exc:
        return CommandResult(ok=False, stdout="", stderr=str(exc))
    return CommandResult(ok=True, stdout="installed", stderr="")


async def apply_new_config(settings: Settings, new_text: str) -> ApplyResult:
    """Stage -> validate -> install. The live config is only ever touched
    after validation succeeds; a failure at either stage leaves it alone."""
    await stage(settings, new_text)

    checked = await check_config(settings)
    if not checked.ok:
        return ApplyResult(ok=False, stage="check", output=checked.stderr or checked.stdout)

    installed = await install_config(settings)
    if not installed.ok:
        return ApplyResult(ok=False, stage="apply", output=installed.stderr or installed.stdout)

    return ApplyResult(ok=True, stage="", output=installed.stdout)


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
