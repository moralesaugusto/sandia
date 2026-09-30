"""Read-only AI assistant backed by a local Ollama server.

The assistant never gets tools or write access: every question is answered
from a plain-text snapshot of Sandia's own data (service status, dhcpd.conf,
leases, DHCP log tail) built server-side and sent as the system prompt.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session

from .config import Settings
from .config_store import load_live_config
from .dhcpd import serialize
from .dhcpd.apply import service_status
from .diagnostics import load_dhcp_events
from .i18n import _, current_language
from .leases import load_leases
from .models import AiSettings

DEFAULT_OLLAMA_PORT = 11434

# Keep the snapshot small enough for a local model's context window.
MAX_CONFIG_CHARS = 20_000
MAX_CONTEXT_LEASES = 200
MAX_LOG_LINES = 150
MAX_HISTORY_MESSAGES = 20

SYSTEM_PROMPT = """\
You are the assistant built into Sandia, a web console for an ISC \
isc-dhcp-server. Answer questions about the DHCP configuration, leases, \
logs and troubleshooting using only the Sandia data below. If the data \
does not show something, say so instead of guessing. You cannot make \
changes: when a change is needed, explain it and point the user to the \
relevant Sandia page (Subnets, Reservations, Leases, Devices, Advanced \
Settings > Raw Config, Diagnostics). Be concise."""


def system_prompt() -> str:
    # The data snapshot stays in English; only the reply language follows the UI.
    return SYSTEM_PROMPT + (" Reply in Spanish." if current_language() == "es" else "")


def load_ai_settings(session: Session) -> AiSettings:
    return session.get(AiSettings, 1) or AiSettings(id=1)


def normalize_ollama_url(value: str) -> str:
    """A bare host or IP becomes http://<host>:11434; a URL with an explicit
    scheme is kept as given (it may sit behind a reverse proxy)."""
    value = value.strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
        parts = urlsplit(value)
        if parts.port is None:
            value = f"http://{parts.netloc}:{DEFAULT_OLLAMA_PORT}{parts.path}"
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(_("Not a valid Ollama address: {value}", value=value))
    parts.port  # noqa: B018 - accessing it raises ValueError on a malformed or out-of-range port
    return value


async def list_models(url: str) -> list[str]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{url}/api/tags")
        response.raise_for_status()
    return sorted(model["name"] for model in response.json().get("models", []))


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text) - limit} more characters)"


async def build_context(settings: Settings) -> str:
    status = await service_status(settings)
    config_text = serialize(load_live_config(settings)).strip() or "(empty or missing)"

    leases = load_leases(settings.leases_path)
    counts = Counter(lease.binding_state or "unknown" for lease in leases)
    active = [lease for lease in leases if lease.is_active]
    lease_lines = [
        f"{lease.ip} {lease.mac or '-'} {lease.hostname or '-'} ends {lease.ends or '-'}"
        for lease in active[:MAX_CONTEXT_LEASES]
    ]
    if len(active) > MAX_CONTEXT_LEASES:
        lease_lines.append(f"... ({len(active) - MAX_CONTEXT_LEASES} more active leases not shown)")

    events, log_unavailable = load_dhcp_events(settings)
    log_text = log_unavailable or "\n".join(event.raw for event in events[-MAX_LOG_LINES:]) or "(no dhcpd lines)"

    return "\n\n".join(
        [
            f"## Service\n{settings.service_name}: {status}",
            f"## dhcpd.conf ({settings.dhcpd_conf_path})\n{_truncate(config_text, MAX_CONFIG_CHARS)}",
            "## Leases\n"
            + (", ".join(f"{state}: {n}" for state, n in sorted(counts.items())) or "no leases")
            + "\nActive leases (IP MAC hostname end-time):\n"
            + ("\n".join(lease_lines) or "(none)"),
            f"## DHCP log (last {MAX_LOG_LINES} dhcpd lines from {settings.dhcp_log_path})\n{log_text}",
        ]
    )


def clean_history(messages: list) -> list[dict]:
    """Keep only well-formed user/assistant turns from the browser - the
    system prompt is always the server's own."""
    cleaned = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
    ]
    return cleaned[-MAX_HISTORY_MESSAGES:]


async def chat_stream(url: str, model: str, messages: list[dict]) -> AsyncIterator[str]:
    """Yield reply text chunks from Ollama's streaming /api/chat. Failures
    are yielded as a visible bracketed line so the user sees them in the
    chat window rather than an empty reply."""
    payload = {"model": model, "messages": messages, "stream": True}
    try:
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=300.0)) as client,
            client.stream("POST", f"{url}/api/chat", json=payload) as response,
        ):
            if response.status_code != 200:
                body = (await response.aread()).decode(errors="replace")
                yield "[" + _("Ollama returned HTTP {status}: {body}", status=response.status_code, body=body[:300]) + "]"
                return
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if "error" in data:
                    yield "\n[" + _("Ollama error: {error}", error=data["error"]) + "]"
                    return
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk
    except httpx.HTTPError as exc:
        yield "\n[" + _("Could not reach Ollama at {url}: {error}", url=url, error=f"{type(exc).__name__}: {exc}") + "]"
