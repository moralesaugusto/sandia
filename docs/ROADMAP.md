# Roadmap

## Phase 1 - SVG subnet/IP visualization (done, this pass)

- Per-subnet SVG grid: one cell per address in the subnet's pool range,
  color-coded by status (free / dynamically leased / reserved / reserved
  and currently leased / denied).
- Right-click context menu per cell, reusing and generalizing the existing
  lease context-menu pattern (moved into `base.html` so any page can use it).
- Client-side search/highlight within the grid (by IP/MAC/hostname).
- Reservations whose fixed address falls outside the pool range are listed
  separately underneath (they still exist and matter, just aren't part of
  the pool grid).
- Linked from the Subnets list and the Dashboard utilization rows.
- Large pools (over ~1024 addresses) fall back to the existing summary bar
  instead of rendering one SVG cell per address - see `DECISIONS.md`.

## Phase 2 - broader context menus (not yet done)

- Right-click on a Reservations-page row (not just via the map), matching
  the same action set as the map's "reserved" cell menu.
- Right-click on a Subnets-page row for subnet-level actions (Map, Edit,
  Delete) instead of only inline links.

## Phase 3 - DHCP troubleshooting view (not yet done)

- Given a MAC or IP, reconstruct what can actually be determined from
  parsed config + leases: subnet selection, reservation match, pool
  membership, address availability, current lease state. Evidence-only -
  no invented diagnostics, matching `CLAUDE.md`'s troubleshooting section.

## Later / not scheduled

- DHCP event log / operational alerts (would need to tail and parse syslog
  output for `dhcpd`, which isn't read anywhere today - real scope, not a
  small addition).
- Server health page, live/real-time updates (would need a push channel -
  today the app is pure request/response + htmx polling-free partials).
- Conflict detection beyond `dhcpd -t`.

Pan/zoom for the SVG grid was considered for Phase 1 and deliberately
deferred: at the current cell-count cap the grid already fits on screen
without it, and adding it would be complexity without a concrete need yet
(see `CLAUDE.md`'s "avoid premature generalization"). Revisit if usage shows
people working with pools consistently near the cap.
