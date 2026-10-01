# Decisions

## SVG grid cell cap (1024 addresses)

The subnet map renders one `<rect>` per address server-side (no client
framework, no canvas). A `/22`-sized pool (1024 addresses) renders in well
under a second and is a reasonable upper bound for a single dhcpd pool in
practice. Above that, the page falls back to the existing utilization bar
with an explanatory note instead of rendering thousands of DOM nodes.
Chosen over virtualization/pagination because it's simpler and the common
case (pools up to a few hundred addresses) never hits it - see `CLAUDE.md`'s
"measure before introducing complex performance infrastructure."

## Map reservations follow existing subnet-nesting convention

The app already treats "a host reservation belongs to a subnet" as "that
`host` block is nested inside that `subnet` block in `dhcpd.conf`" (see
`reservations.py::_host_subnet_map`, used for the Reservations page subnet
filter). The subnet map reuses the same convention rather than inventing a
second definition (e.g. "any reservation whose IP falls within the range").
A reservation nested elsewhere with an IP that happens to fall in this
subnet's range is out of scope for this map, consistent with how the rest
of the app already reasons about subnet membership.

## Context-menu JS moved to base.html

The floating context-menu container and open/close JS lived in
`leases/list.html` only. The subnet map needed the identical mechanism, so
it was generalized into `base.html` (`openContextMenu(evt, url)` /
`closeContextMenu()`) and the leases page updated to use it instead of its
own copy. This removes duplication rather than adding a second
implementation.

## Status color mapping

Reuses the app's existing brand palette rather than introducing new colors:
free = slate (matches existing empty-state gray), dynamically leased =
emerald (matches "active" badges elsewhere), reserved = pink (matches
"reserved" badge on the Leases page), reserved *and* currently leased =
purple (a distinct fourth state - blend of the two), denied = red (matches
existing error/destructive color).

## Diagnostics: no AI, one root cause, priority-ordered rules

`diagnostics/client.py::_root_cause_findings()` is a plain if/elif chain
over already-parsed evidence, checked in a fixed priority order (reservation
IP conflict > explicit DHCPNAK from the log > pool exhaustion > address not
covered by any subnet > DHCPDISCOVER with no offer). The first rule that
applies is reported as *the* root cause; later rules are not also reported
even if their symptoms are technically also present, so a client with a
reservation conflict doesn't also get told the pool "looks" exhausted. This
is the direct implementation of "when multiple symptoms share a cause,
report the cause once" - and it's deterministic and unit-testable per rule,
which an LLM-based diagnosis would not be.

## Confidence is about the evidence, not the conclusion

`Confidence.CONFIRMED` means "this fact was computed/observed directly from
parsed data" (a count, a config value, a log line that literally says X) -
not "we're sure this is the whole story." E.g. the server's "recent DHCP
errors" finding is CONFIRMED that N log lines matched keywords, but its
root-cause text only claims that much, explicitly deferring the actual
cause to the operator reading the lines - it never claims CONFIRMED about
something it only inferred. `Confidence.STRONG`/`POSSIBLE` are used when a
log line's own reason text is missing and the finding is inferring from
context (e.g. "DISCOVER logged, no OFFER ever followed" without a reason
in the log is POSSIBLE, not STRONG - could be this client, could be
something the log doesn't capture at all).

## DHCP log is optional evidence, not a dependency

`SANDIA_DHCP_LOG_PATH` (default `/var/log/syslog`) is read best-effort,
same precedent as the OUI vendor cache: if it's missing, unreadable, or
just doesn't mention a given client, every check still runs against
config/leases alone and explicitly reports the log gap (a Warning on the
server page; "insufficient evidence"/Unknown steps in client diagnostics)
rather than silently doing less or crashing. A tail-only read (last 2MB,
`diagnostics/dhcp_log.py::MAX_LOG_BYTES`) keeps this bounded regardless of
how large the real syslog is.

## Pool-level diagnostics live on the subnet route, not a separate one

The app models a pool as a property of a subnet (its `range`), not a
separate entity - there's nowhere for a standalone "pool" object to live.
"Diagnose Pool" and "Diagnose Subnet" both resolve to
`/subnets/<key>/diagnose`, which reports both subnet-level (invalid/
overlapping range, interface mismatch, invalid reservations) and
pool-level (exhaustion, utilization, abandoned leases) findings together,
rather than inventing a separate pool resource to justify a separate URL.

## Devices is a view, not a new data model

`devices.py::build_devices()` produces `Device` objects assembled entirely
from the existing `Host` (reservations), `Lease` (current + full history,
via the new `parse_lease_history()`/`load_lease_history()` in `leases.py`),
and `DhcpEvent` (diagnostics' log parser) types. A `Device` holds
references to a `Host`/`Lease`, never copies of their fields - so there is
exactly one place each fact comes from. MAC is the identity: a device is
the union of every MAC seen in reservations, current leases, or lease
history, not a per-IP or per-lease row.

## "Release Lease" became "Delete lease record"

Sandia has no OMAPI or other live channel to a running dhcpd - every
existing write capability (apply config, "Clean leases") is a plain file
edit, backed up first, never a live protocol command. There is no safe way
to force-revoke a lease a client is actively holding. Rather than fake a
"Release" action that can't do what its name promises, the device menu
offers "Delete lease record": it removes Sandia's copy of the current
lease block(s) from the leases file (same backup-first text-surgery
pattern as `leases_cleanup.clean_leases_text()`, via the new
`delete_lease_records()`), and both the confirmation dialog and the
success message say plainly that if the device is still active, dhcpd
will simply write a new record on its next renewal. "Deny this client"
(the existing config-based mechanism) remains the answer for actually
blocking a device.

## Device status is a fixed priority chain over real timestamps

`devices.py::_build_status()` picks exactly one of Problem / Active /
Recently seen / Inactive / Reserved / Unknown, in that priority order,
from `current_lease.is_active`, `last_seen` (computed only from parseable
`starts` timestamps in lease history - never from the DHCP log, whose
timestamps lack a year and aren't reliably sortable), and whether a
reservation exists. "Recently seen" vs "Inactive" is a fixed 24-hour
threshold (`RECENT_WINDOW`), not a tunable heuristic. Reservation-having
and lease-having are also shown as their own table columns/filters, so
folding them into the status enum too would be redundant - status answers
"how urgently does this device need attention", not "what do we know
about it".

## Lease IP reuses the reservation form; it does not add a second one

`GET /devices/<mac>/lease` only computes context (suggested next-free
address via `ip_map.next_available_ip()`, pool utilization, a warning if
the device's active lease is on a different subnet) and links to the
existing `/reservations/new` route - the extra `subnet_key` prefill
parameter is the only change to that route. If the device already has a
reservation, this route redirects straight to editing it rather than
rendering a form that could create a conflicting second one.

## Wall of Shame: syslog timestamps are assumed to be the current year

dhcpd's syslog lines have no year (`Sep  2 09:00:00`), which is exactly
why `diagnostics/dhcp_log.py`'s events were never sorted/filtered by time
before this feature (see the "DHCP log is optional evidence" decision
above). Wall of Shame's time-range filter needs *some* real timestamp to
filter on, so `wall_of_shame.parse_syslog_timestamp()` assumes the
current year and rolls back one year if that would place the event in
the future - the same convention every standard syslog reader uses for
this format, not a guess about the event itself. This is a reasonable
trade-off given Sandia already only reads the tail of the log
(`MAX_LOG_BYTES`), which in practice covers at most a few days to weeks -
the year-boundary edge case this heuristic exists for is rare, and wrong
only right at a rotation that happens to straddle midnight on Dec 31.
Lease-history timestamps (used for IP changes and abandoned leases) don't
have this problem - `starts`/`ends` in `dhcpd.leases` always include the
year, so those two lists use exact dates, not an assumption.

## Wall of Shame: what counts as an "IP change"

A device's lease history is walked in chronological order; a "change" is
counted only when a record's address differs from the *immediately
preceding* record's address for that MAC. A renewal (dhcpd appends a new
block for the same IP on lease refresh) never counts, because consecutive
records share the same address. This needed no new concept - it's the
same historical data `devices.py::Device.history`/`previous_ips` already
expose, just walked once to count transitions instead of only listing them.

## Light/dark mode: remap color tokens via CSS variables, not `dark:` classes

The app is styled entirely with literal Tailwind utility classes
(`bg-slate-900`, `text-emerald-400`, ...), never `dark:`-prefixed variants -
there was no light palette to fall back to. Rewriting ~35 templates to carry
a second set of classes would be a large, error-prone change for a purely
cosmetic feature. Instead, `base.html` overrides `tailwind.config.theme`
so the `slate` palette (every background/border/text token in the app) and
the four accent shades actually used as plain status text (`pink-400`,
`emerald-400`, `amber-400`, `red-400`) resolve to CSS custom properties;
`html.light` redefines those properties to a readable value for a light
background. No template changes color classes at all - toggling is just
adding/removing one class on `<html>`. Accent shades used inside their own
self-contained tinted box (toasts, validation banners - `bg-red-950
text-red-300 border-red-900` and similar) were deliberately left as literal,
unvaried colors: they're already high-contrast internally regardless of
page theme, and remapping only one shade in that trio would have broken
them. `text-white` on the app's solid/gradient brand buttons (always a
saturated background, in either theme) was left alone for the same reason;
every other bare `text-white`/`hover:text-white` (assumed a dark hover
background) was changed to `text-slate-100`, which does invert, so hover
states stay legible in light mode instead of turning invisible on a now-light
background.

## Light/dark mode: saved in the session first, the account second

The choice is written to `request.session["theme"]` on every toggle (works
immediately, including on the login page before any user is known) and,
only when a user is authenticated, mirrored to `User.theme` in the database.
On login, `request.session.setdefault("theme", user.theme)` seeds the new
session from the account's saved preference *without* overwriting a choice
already made earlier in that same anonymous session - a device the user is
sitting at right now should keep winning over a stale account-level value
they might not even remember setting. This gives the behavior implied by
"save this setting": correct on the very first request with no account yet,
and durable across browsers/devices once one exists. `User.theme` is added
via a small idempotent `ALTER TABLE ... ADD COLUMN` guard in
`db.py::_ensure_user_theme_column()` rather than a migration framework -
`SQLModel.metadata.create_all()` only creates missing tables, never adds
columns to one that already exists, and this is the only schema change this
project has needed since the original `User`/`AuditLog` tables.

## Wall of Shame: abandoned-lease device association is never invented

An abandoned lease block sometimes carries `hardware ethernet` (a client
that got denied/declined) and sometimes doesn't (e.g. dhcpd detected a
ping conflict before ever offering the address to a client - nobody to
blame). Rows are grouped by MAC only when the record actually has one;
otherwise the row is the bare IP with no device link, exactly matching
the instruction to show the address rather than fabricate a relationship.

## Apply restarts, verifies, and rolls back automatically

Every apply already took a backup before installing, but stopped there and
told the operator to restart - so a config that passed `dhcpd -t` but still
failed at startup (e.g. an interface that doesn't exist) left the server
down until someone noticed. `apply_new_config()` now restarts the service
and checks `systemctl is-active`; on failure it reinstalls the backup it
just took and restarts again, reporting both outcomes. The install is a
copy to a sibling temp file plus `os.replace`, so the live file is never
partially written. A first-ever install has no backup, and says so rather
than pretending to roll back.

## AI assistant: read-only, context built by the server

The assistant gets no tools and no write path: each question is sent to
Ollama with a system prompt the server builds from the same loaders the
rest of the app uses (service status, serialized `dhcpd.conf`, active
leases, DHCP log tail), each section capped so it fits a small local
model's context window. The browser only sends user/assistant turns;
anything else (including a client-supplied `system` role) is dropped
server-side. This keeps it consistent with "never invent diagnostic
information" - it can only reason over real data, and every change still
goes through the existing validate/diff/apply workflow. Tool calling was
not used because it depends on model support and adds a loop for little
gain at this data size. Settings live in a single-row `AiSettings` table
(created by `create_all`, no migration needed), admin-only because the
configured server receives the full config with every question.

## Translation: a dict catalog, not gettext

Two languages don't justify Babel/gettext's `.po` -> `.mo` compile step,
which would break the "no build step" rule. English source strings are the
keys (`_("Save")`), so English needs no catalog and a missing Spanish entry
falls back to English; `i18n_es.ES` maps them to Spanish. The language is a
contextvar set once per request by a small ASGI middleware (inside
`SessionMiddleware`), so the same `_()` works in templates, routers and the
diagnostics engine. Templates use `template_gettext`, which escapes only the
`{placeholder}` values (via `Markup.format`) and not the trusted catalog
text, so quotes in messages render as before. Module-level label tables use
`N_()` (a no-op marker) and are passed through `_()` at display time.
`tests/test_i18n.py` scans every `_()`/`N_()` literal and fails if one has no
Spanish entry or if a translation drops a placeholder.

What stays English in the Spanish UI: acronyms, config keywords, paths,
data values (IPs, MACs, hostnames, log lines), audit action identifiers,
CSV headers, the AI assistant's data snapshot, and the terms lease,
subnet, pool, host and gateway (as Spanish-speaking sysadmins say them).
The tagline stays English because it is the SANDIA backronym.

## Kea is the supported backend; ISC is legacy

From 1.4.5, Kea DHCPv4 is the default (`SANDIA_DHCP_BACKEND=kea`) and the
only supported server. ISC DHCP reached end of maintenance upstream in 2022.
The ISC backend stays selectable (`isc`) so existing installs can migrate
on their own schedule, but it gets no new work. Where a change can't serve
both, Kea's behavior wins.

The backend is read once at startup, like every other setting. The paths
and service name it changes are resolved in `Settings.__post_init__`, so an
explicit env var or argument still wins. It isn't stored in the DB or
editable in the UI, because switching live would mean re-resolving paths
and services mid-flight.

Everything that differs is a field of `dhcpd/backend.py:Backend`: validator,
config parse/render, lease and log parsers, lease deletion, listening
interfaces. Callers ask the backend instead of branching on its name.

## Kea editing: one config model, patched back into the JSON

The editors keep working on the existing config model (`dhcpd/ast.py`).
`kea.parse_kea_config` projects `kea-dhcp4.conf` into it, field by field,
for everything with an exact Kea equivalent. `kea.render_kea_config` maps
the edited model back onto the original JSON, and `kea_edit.patch_json`
rewrites only the values that changed. So comments, formatting and every
key Sandia doesn't model survive an edit, and the diff of an applied change
is as small as the change itself.

A dedicated Kea data model and per-form JSON writers would have meant a
second copy of every editor. One projection keeps the map, devices,
diagnostics and every editor shared.

Content with no Kea equivalent is refused with a message, never dropped:
an extra-options statement that isn't an `option`, or Deny when a
hand-written `DROP` class exists. Configs with `<?include?>` are read by
following the includes (as `kea-dhcp4` does, relative to `/`) but not
patched, because the edit might belong in the included file.

Deny uses the `DROP` client class with a `pkt4.mac == 0x...` test (documented
in Kea's classification chapter: a packet in DROP is dropped). That is used
instead of host reservations, which would also need
`early-global-reservations-lookup`.

## Kea runtime operations go through the control socket

Lease deletion is `lease4-del` and config activation is `config-reload`,
both over `control-socket`, the supported way to change a running Kea.
Sandia never edits `kea-leases4.csv`. Without a socket, applies use
`systemctl restart` (explicitly reported as such), and lease deletion fails
with the connection error rather than silently doing nothing. Kea compacts
its own lease file, so there's no Clean leases for Kea.

Debian's packaged Kea logs to stdout, so the default Kea log source is the
service's journal (`journalctl -u`). Log lines are normalized into the same
`DhcpEvent` shape, with syslog-style timestamps, so the Event Log and Wall of
Shame don't know the source. Fields Kea doesn't log (hostname, interface)
stay `None`.
