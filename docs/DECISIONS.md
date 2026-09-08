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

## Wall of Shame: abandoned-lease device association is never invented

An abandoned lease block sometimes carries `hardware ethernet` (a client
that got denied/declined) and sometimes doesn't (e.g. dhcpd detected a
ping conflict before ever offering the address to a client - nobody to
blame). Rows are grouped by MAC only when the record actually has one;
otherwise the row is the bare IP with no device link, exactly matching
the instruction to show the address rather than fabricate a relationship.
