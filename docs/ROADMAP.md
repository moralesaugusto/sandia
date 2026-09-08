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

## Phase 2 - broader context menus (done, this pass)

- Right-click on a Reservations-page row (new `reservations/_menu.html`),
  offering Diagnose/Edit/Delete/copy - the same shared `openContextMenu()`
  mechanism as leases and the subnet map, not a second implementation.
- Subnets-page rows gained a "Diagnose" inline link alongside the existing
  Map/Edit/Delete links (that page's established pattern is inline links,
  not a context menu - kept consistent rather than introducing a second
  interaction style on one page).

## Phase 3 - DHCP diagnostics (done, this pass)

- `src/sandia/diagnostics/`: deterministic, evidence-based checks for the
  server, a subnet/pool, and a client - never an LLM, never a guess
  presented as fact. See `DECISIONS.md` for the root-cause priority order.
- Client diagnostics ("why didn't this client get an IP?") reconstructs
  the flow from config/leases and, where available, a parsed DHCP syslog
  (`SANDIA_DHCP_LOG_PATH`) - the first thing in this app to read DHCP
  protocol activity (DISCOVER/OFFER/REQUEST/ACK/NAK/DECLINE/RELEASE), not
  just lease *state*.
- Wired into the existing context-menu system throughout (leases, subnet
  map, reservations) plus buttons on Subnets/Service pages - see
  `CHANGELOG.md` 1.0.9.

## Phase 4 - Devices workspace (done, this pass)

- `devices.py`: correlates reservations, current leases, full lease
  history, and DHCP log activity into one row per MAC - not a new data
  model, a view over the existing `Host`/`Lease`/`DhcpEvent` types.
  `/devices` (search/filter/sort/export/bulk-select) and `/devices/<mac>`
  (Device 360). See `DECISIONS.md` for the status model and why "Release
  Lease" became "Delete lease record".
- "Lease IP" reuses the existing `/reservations/new` form (extended with a
  `subnet_key` prefill) rather than a parallel reservation flow; it only
  adds a context page that suggests a free address first.
- Every context menu that identifies a MAC (leases, subnet map, now
  reservations too) gained "Open device"/"Diagnose device"; the Dashboard
  gained device-count/device-problem tiles reusing the existing tile
  pattern and the same problem signals diagnostics already computes.

## Later / not scheduled

- A real DHCP event *log page* (browsing/filtering all parsed log events,
  not just a given client's) - the parser now exists (`diagnostics/dhcp_log.py`)
  but there's no UI surface for it beyond per-client/per-server/per-device
  diagnostics and activity views.
- Server health page beyond what `/diagnostics/server` already reports,
  live/real-time updates (would need a push channel - today the app is
  pure request/response + htmx polling-free partials).
- Conflict/anomaly detection beyond what's implemented in
  `diagnostics/subnet.py` (duplicate reservations, overlapping/invalid
  ranges, interface mismatches, abandoned/exhausted pools).
- Bulk reservation creation for multiple selected devices - deferred
  deliberately (see `DECISIONS.md`): each device needs its own target IP,
  which is real per-device decision-making, not a mechanical loop like
  bulk lease-record deletion.
- Pagination/virtualization for the Devices table - not added; it follows
  the same precedent as Leases/Reservations (search/filter to narrow down,
  render the rest server-side). Revisit only if real inventories are large
  enough that this stops being fast enough in practice.

Pan/zoom for the SVG grid was considered for Phase 1 and deliberately
deferred: at the current cell-count cap the grid already fits on screen
without it, and adding it would be complexity without a concrete need yet
(see `CLAUDE.md`'s "avoid premature generalization"). Revisit if usage shows
people working with pools consistently near the cap.
