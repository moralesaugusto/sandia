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
