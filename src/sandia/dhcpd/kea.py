"""Adapters for Kea DHCPv4 files (kea-dhcp4.conf, memfile leases).

The config is projected into the app's config model (dhcpd/ast.py) for every
field that has an exact Kea equivalent - subnets, pools, option-data,
lifetimes, PXE fields, the subnet interface, reservations, `authoritative`,
and denied clients (the DROP class). render_kea_config() maps an edited
model back onto the original JSON through kea_edit.patch_json(), so only
what changed is rewritten: comments and keys Sandia doesn't model survive.
"""

from __future__ import annotations

import copy
import csv
import io
import ipaddress
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from ..leases import Lease
from .ast import Comment, DhcpdConfig, Host, Option, Parameter, Subnet
from .kea_edit import patch_json
from .parser import ParseError
from .subnet_interface import get_subnet_interface


def _string_end(text: str, start: int) -> int:
    """Index just past the JSON string starting at text[start] == '"'."""
    i = start + 1
    while i < len(text) and text[i] != '"':
        i += 2 if text[i] == "\\" else 1
    return i + 1


def to_plain_json(text: str) -> str:
    """Remove the extensions Kea's parser accepts on top of JSON - `#`, `//`
    and `/* */` comments, and trailing commas (Debian's packaged
    kea-dhcp4.conf has one) - leaving string contents untouched."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            end = _string_end(text, i)
            out.append(text[i:end])
            i = end
        elif c == "#" or text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(c)
            i += 1
    stripped = "".join(out)

    out = []
    i, n = 0, len(stripped)
    while i < n:
        c = stripped[i]
        if c == '"':
            end = _string_end(stripped, i)
            out.append(stripped[i:end])
            i = end
            continue
        if c == ",":
            j = i + 1
            while j < n and stripped[j].isspace():
                j += 1
            if j < n and stripped[j] in "}]":
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


_INCLUDE_RE = re.compile(r'<\?include\s+"([^"]+)"\s*\?>')
# kea-dhcp4 resolves a relative include path against its working directory,
# which is "/" when systemd starts it (the packaged unit sets none).
INCLUDE_BASE = Path("/")
_MAX_INCLUDE_DEPTH = 10  # Kea's own limit


def _expand_includes(text: str, depth: int = 0) -> str:
    def load(match: re.Match) -> str:
        if depth >= _MAX_INCLUDE_DEPTH:
            raise ParseError("Kea config nests <?include?> more than 10 levels deep")
        path = INCLUDE_BASE / match.group(1)
        try:
            included = path.read_text()
        except OSError as exc:
            raise ParseError(f"cannot read included file {path}: {exc}") from exc
        return _expand_includes(to_plain_json(included), depth + 1)

    return _INCLUDE_RE.sub(load, text)


def _load_json(text: str) -> dict:
    try:
        data = json.loads(to_plain_json(_expand_includes(to_plain_json(text))))
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid Kea JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ParseError("Kea config must be a JSON object")
    return data


def _unquote(value: str) -> str:
    value = value.strip()
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


def _pool_range(pool: str) -> str:
    if "-" in pool:
        first, last = (part.strip() for part in pool.split("-", 1))
        return f"{first} {last}"
    network = ipaddress.ip_network(pool.strip(), strict=False)
    return f"{network[0]} {network[-1]}"


# Model parameter -> Kea key, for every parameter Sandia's forms manage.
_PARAMS = {
    "default-lease-time": "valid-lifetime",
    "max-lease-time": "max-valid-lifetime",
    "next-server": "next-server",
    "filename": "boot-file-name",
}
_INT_PARAMS = {"default-lease-time", "max-lease-time"}
_HOST_PARAMS = {"next-server", "filename"}  # Kea reservations have no lifetimes

_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")
_DROP_TERM_RE = re.compile(r"^pkt4\.mac\s*==\s*0x([0-9a-fA-F]{12})$")


def _managed_options(entries: list) -> list[dict]:
    return [e for e in entries if "name" in e and "data" in e and e.get("space", "dhcp4") == "dhcp4"]


def _project_params(source: dict, names) -> list[Parameter]:
    return [Parameter(name, str(source[_PARAMS[name]])) for name in names if _PARAMS[name] in source]


def _reservation_name(reservation: dict) -> str | None:
    return reservation.get("hostname") or reservation.get("hw-address") or reservation.get("ip-address")


def _host(reservation: dict) -> Host | None:
    name = _reservation_name(reservation)
    if not name:
        return None
    host = Host(name)
    if reservation.get("hw-address"):
        host.set_mac(reservation["hw-address"].lower())
    if reservation.get("ip-address"):
        host.set_fixed_address(reservation["ip-address"])
    host.body.extend(_project_params(reservation, _HOST_PARAMS))
    host.body.extend(Option(o["name"], str(o["data"])) for o in _managed_options(reservation.get("option-data", [])))
    return host


def _subnet(entry: dict) -> Subnet:
    network = ipaddress.ip_network(entry["subnet"], strict=False)
    subnet = Subnet(str(network.network_address), str(network.netmask))
    for pool in entry.get("pools", []):
        subnet.body.append(Parameter("range", _pool_range(pool["pool"])))
    subnet.body.extend(_project_params(entry, _PARAMS))
    subnet.body.extend(Option(o["name"], str(o["data"])) for o in _managed_options(entry.get("option-data", [])))
    for reservation in entry.get("reservations", []):
        host = _host(reservation)
        if host:
            subnet.body.append(host)
    return subnet


def _drop_macs(dhcp4: dict) -> list[str] | None:
    """MACs denied by a DROP class Sandia can manage (a test made only of
    `pkt4.mac == 0x...` terms joined by `or`); None for a hand-written DROP
    class, which Sandia leaves alone."""
    for cls in dhcp4.get("client-classes", []):
        if cls.get("name") != "DROP":
            continue
        if set(cls) - {"name", "test"}:
            return None
        macs = []
        for term in re.split(r"\s+or\s+", str(cls.get("test", "")).strip()):
            match = _DROP_TERM_RE.match(term.strip())
            if not match:
                return None
            raw = match.group(1).lower()
            macs.append(":".join(raw[i : i + 2] for i in range(0, 12, 2)))
        return macs
    return []


def deny_host_name(mac: str) -> str:
    return f"deny-{mac.replace(':', '')}"


def parse_kea_config(text: str) -> DhcpdConfig:
    dhcp4 = _load_json(text).get("Dhcp4", {})
    config = DhcpdConfig()
    if dhcp4.get("authoritative") is True:
        config.nodes.append(Parameter("authoritative", ""))
    config.nodes.extend(_project_params(dhcp4, _PARAMS))
    config.nodes.extend(Option(o["name"], str(o["data"])) for o in _managed_options(dhcp4.get("option-data", [])))
    for reservation in dhcp4.get("reservations", []):
        host = _host(reservation)
        if host:
            config.nodes.append(host)
    for mac in _drop_macs(dhcp4) or []:
        host = Host(deny_host_name(mac))
        host.set_mac(mac)
        host.body.append(Parameter("deny", "booting"))
        config.nodes.append(host)
    subnets = list(dhcp4.get("subnet4", []))
    for shared in dhcp4.get("shared-networks", []):
        subnets.extend(shared.get("subnet4", []))
    try:
        for entry in subnets:
            if entry.get("interface"):
                config.nodes.append(Comment(f"interface: {entry['interface']}"))
            config.nodes.append(_subnet(entry))
    except (KeyError, TypeError, ValueError) as exc:
        raise ParseError(f"unsupported subnet4 entry: {exc}") from exc
    return config


def configured_interfaces(text: str) -> list[str]:
    """Dhcp4.interfaces-config.interfaces - Kea's equivalent of ISC's
    INTERFACESv4, but part of the config file itself."""
    return list(_load_json(text).get("Dhcp4", {}).get("interfaces-config", {}).get("interfaces", []))


# --- writing -------------------------------------------------------------------


def _write_params(target: dict, params: list[Parameter], names) -> None:
    values = {}
    for param in params:
        if param.name not in names:
            raise ValueError(f"'{param.name}' has no Kea setting Sandia can write here - use the Raw Config page")
        if param.name in _INT_PARAMS:
            try:
                values[_PARAMS[param.name]] = int(param.value)
            except ValueError:
                raise ValueError(f"{param.name} must be a whole number of seconds") from None
        else:
            values[_PARAMS[param.name]] = _unquote(param.value)
    for name in names:
        key = _PARAMS[name]
        if key in values:
            target[key] = values[key]
        else:
            target.pop(key, None)


def _write_options(target: dict, options: list[Option]) -> None:
    wanted = {option.name: _unquote(option.value) for option in options}
    managed = {id(e) for e in _managed_options(target.get("option-data", []))}
    result = []
    for entry in target.get("option-data", []):
        if id(entry) not in managed:
            result.append(entry)
        elif entry["name"] in wanted:
            result.append({**entry, "data": wanted.pop(entry["name"])})
    result.extend({"name": name, "data": data} for name, data in wanted.items())
    if result or "option-data" in target:
        target["option-data"] = result


def _write_reservation(host: Host, reservation: dict) -> dict:
    if host.mac:
        if (reservation.get("hw-address") or "").lower() != host.mac.lower():
            reservation["hw-address"] = host.mac
    else:
        reservation.pop("hw-address", None)
    if host.fixed_address:
        reservation["ip-address"] = host.fixed_address
    else:
        reservation.pop("ip-address", None)
    params = [n for n in host.body if isinstance(n, Parameter) and n.name not in ("hardware", "fixed-address")]
    _write_params(reservation, params, _HOST_PARAMS)
    _write_options(reservation, [n for n in host.body if isinstance(n, Option)])
    return reservation


def _write_reservations(target: dict, hosts: list[Host]) -> None:
    by_name = {host.name: host for host in hosts}
    result = []
    for reservation in target.get("reservations", []):
        name = _reservation_name(reservation)
        if name is None:
            result.append(reservation)  # not something Sandia projects
        elif name in by_name:
            result.append(_write_reservation(by_name.pop(name), reservation))
    result.extend(_write_reservation(host, {"hostname": host.name}) for host in by_name.values())
    if result or "reservations" in target:
        target["reservations"] = result


def _write_pools(entry: dict, ranges: list[str]) -> None:
    wanted = [" ".join(value.split()) for value in ranges]
    result = []
    for pool in entry.get("pools", []):
        try:
            normalized = _pool_range(pool["pool"])
        except (KeyError, ValueError):
            result.append(pool)
            continue
        if normalized in wanted:
            wanted.remove(normalized)
            result.append(pool)
    for value in wanted:
        first, last = value.split()
        result.append({"pool": f"{first} - {last}"})
    if result or "pools" in entry:
        entry["pools"] = result


def _write_subnet(config: DhcpdConfig, subnet: Subnet, entry: dict) -> None:
    params = [n for n in subnet.body if isinstance(n, Parameter)]
    _write_pools(entry, [p.value for p in params if p.name == "range"])
    _write_params(entry, [p for p in params if p.name != "range"], _PARAMS)
    _write_options(entry, [n for n in subnet.body if isinstance(n, Option)])
    interface = get_subnet_interface(config, subnet)
    if interface:
        entry["interface"] = interface
    else:
        entry.pop("interface", None)
    _write_reservations(entry, subnet.hosts)


def _subnet_key(entry: dict) -> str | None:
    try:
        network = ipaddress.ip_network(entry["subnet"], strict=False)
    except (KeyError, TypeError, ValueError):
        return None
    return f"{network.network_address}_{network.netmask}"


def _write_subnets(dhcp4: dict, config: DhcpdConfig) -> None:
    edited = {subnet.key: subnet for subnet in config.subnets}
    containers = [dhcp4.get("subnet4", [])] + [shared.get("subnet4", []) for shared in dhcp4.get("shared-networks", [])]
    ids = [entry["id"] for container in containers for entry in container if isinstance(entry.get("id"), int)]
    next_id = max(ids, default=0) + 1
    for container in containers:
        kept = []
        for entry in container:
            key = _subnet_key(entry)
            if key is None:
                kept.append(entry)
            elif key in edited:
                _write_subnet(config, edited.pop(key), entry)
                kept.append(entry)
        container[:] = kept
    for subnet in edited.values():
        prefix = ipaddress.ip_network(f"{subnet.network}/{subnet.netmask}", strict=False).prefixlen
        entry = {"id": next_id, "subnet": f"{subnet.network}/{prefix}"}
        next_id += 1
        _write_subnet(config, subnet, entry)
        dhcp4.setdefault("subnet4", []).append(entry)


def _write_drop(dhcp4: dict, macs: list[str]) -> None:
    current = _drop_macs(dhcp4)
    if current is None:
        if macs:
            raise ValueError("kea-dhcp4.conf already has a hand-written DROP class - deny clients on the Raw Config page")
        return
    classes = dhcp4.get("client-classes", [])
    index = next((i for i, cls in enumerate(classes) if cls.get("name") == "DROP"), None)
    if not macs:
        if index is not None:
            classes.pop(index)
        return
    for mac in macs:
        # It becomes part of a Kea expression, so only a plain MAC is accepted.
        if not _MAC_RE.match(mac):
            raise ValueError(f"'{mac}' is not a MAC address (aa:bb:cc:dd:ee:ff)")
    test = " or ".join(f"pkt4.mac == 0x{mac.replace(':', '').lower()}" for mac in macs)
    if index is None:
        dhcp4.setdefault("client-classes", []).append({"name": "DROP", "test": test})
    elif classes[index].get("test") != test:
        classes[index]["test"] = test


def _load_for_write(text: str) -> dict:
    if "<?include" in to_plain_json(text):
        raise ParseError("this Kea config uses <?include?>; edit it on the Raw Config page")
    return _load_json(text) if text.strip() else {}


def render_kea_config(text: str, config: DhcpdConfig) -> str:
    """The original kea-dhcp4.conf text with the edits made to its projection
    applied. Raises ValueError for model content with no Kea equivalent."""
    old = _load_for_write(text)
    new = copy.deepcopy(old)
    dhcp4 = new.setdefault("Dhcp4", {})

    params = [n for n in config.nodes if isinstance(n, Parameter)]
    if any(p.name == "authoritative" for p in params):
        dhcp4["authoritative"] = True
    elif dhcp4.get("authoritative") is True:
        del dhcp4["authoritative"]
    _write_params(dhcp4, [p for p in params if p.name != "authoritative"], _PARAMS)
    _write_options(dhcp4, [n for n in config.nodes if isinstance(n, Option)])

    hosts = config.top_level_hosts
    denied = [host for host in hosts if host.get("deny") == "booting"]
    _write_reservations(dhcp4, [host for host in hosts if host not in denied])
    _write_drop(dhcp4, [host.mac for host in denied if host.mac])
    _write_subnets(dhcp4, config)
    return patch_json(text, old, new)


def set_kea_interfaces(text: str, interfaces: list[str]) -> str:
    old = _load_for_write(text)
    new = copy.deepcopy(old)
    new.setdefault("Dhcp4", {}).setdefault("interfaces-config", {})["interfaces"] = interfaces
    return patch_json(text, old, new)


# Kea memfile `state` column -> the ISC binding-state term the rest of the
# app already uses for the same meaning.
_STATES = {"0": "active", "1": "abandoned", "2": "free", "3": "released"}


def _isc_timestamp(epoch: int) -> str:
    # Same shape (and UTC, like dhcpd writes) as dhcpd.leases, so
    # leases.parse_lease_timestamp() handles both backends.
    moment = datetime.fromtimestamp(epoch, UTC)
    return f"{moment.isoweekday() % 7} {moment:%Y/%m/%d %H:%M:%S}"


def _parse_rows(text: str) -> list[Lease]:
    """Every row in file order. Memfile appends a row on every change, and
    a row with valid_lifetime 0 when a lease is deleted (binding_state None
    here)."""
    records = []
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("address") == "address":
            continue  # header repeated when files are concatenated
        try:
            expire = int(row["expire"])
            lifetime = int(row["valid_lifetime"])
        except (KeyError, TypeError, ValueError):
            continue
        state = row.get("state") or ""
        records.append(
            Lease(
                ip=row["address"],
                mac=(row.get("hwaddr") or "").lower() or None,
                hostname=(row.get("hostname") or "").replace("&#x2c", ",") or None,
                starts=_isc_timestamp(expire - lifetime),
                ends=_isc_timestamp(expire),
                binding_state=_STATES.get(state, state) if lifetime else None,
            )
        )
    return records


def parse_kea_lease_history(text: str) -> list[Lease]:
    return [record for record in _parse_rows(text) if record.binding_state is not None]


def parse_kea_leases(text: str) -> list[Lease]:
    by_ip: dict[str, Lease] = {}
    for record in _parse_rows(text):
        if record.binding_state is None:
            by_ip.pop(record.ip, None)
        else:
            by_ip[record.ip] = record
    return list(by_ip.values())


def read_kea_leases_text(path: Path) -> str:
    """The files Kea itself loads on startup, in its order: the LFC output
    (`.completed` if LFC just finished, else `.2` and the `.1` snapshot LFC
    is working on), then the live file Kea appends to."""
    completed = path.with_name(path.name + ".completed")
    if completed.exists():
        candidates = [completed, path]
    else:
        candidates = [path.with_name(path.name + ".2"), path.with_name(path.name + ".1"), path]
    parts = []
    for candidate in candidates:
        if candidate.exists():
            text = candidate.read_text()
            parts.append(text if text.endswith("\n") or not text else text + "\n")
    return "".join(parts)
