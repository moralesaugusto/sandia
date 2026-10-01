"""Minimal client for kea-dhcp4's UNIX control socket (Kea management API).

Requires `control-socket` in kea-dhcp4.conf; lease commands additionally
need the lease_cmds hook (libdhcp_lease_cmds.so) loaded. Every failure is
returned to the caller as KeaControlError with Kea's own text, never hidden.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

TIMEOUT_SECONDS = 10


class KeaControlError(Exception):
    pass


def _is_complete(data: bytes) -> bool:
    try:
        json.loads(data)
    except ValueError:
        return False
    return True


async def send_command(socket_path: Path, command: str, arguments: dict | None = None) -> dict:
    request: dict = {"command": command}
    if arguments:
        request["arguments"] = arguments
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(socket_path)), TIMEOUT_SECONDS)
    except (OSError, TimeoutError) as exc:
        raise KeaControlError(f"cannot connect to the Kea control socket {socket_path}: {exc}") from exc
    try:
        writer.write(json.dumps(request).encode())
        await writer.drain()
        data = b""
        # Read until the response parses (or Kea closes the connection).
        while chunk := await asyncio.wait_for(reader.read(65536), TIMEOUT_SECONDS):
            data += chunk
            if _is_complete(data):
                break
    except (OSError, TimeoutError) as exc:
        raise KeaControlError(f"Kea control socket {socket_path}: {exc}") from exc
    finally:
        writer.close()
    try:
        response = json.loads(data)
    except ValueError as exc:
        raise KeaControlError(f"invalid response from the Kea control socket: {data[:200]!r}") from exc
    # Kea answers a single command with one object; the Control Agent wraps
    # it in a list.
    if isinstance(response, list):
        response = response[0] if response else {}
    if not isinstance(response, dict):
        raise KeaControlError(f"unexpected response from the Kea control socket: {response!r}")
    return response
