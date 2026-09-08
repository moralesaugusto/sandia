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
