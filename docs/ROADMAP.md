# Roadmap

## Phase 1 - SVG subnet/IP visualization (done, 1.0.8)

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

## Phase 2 - broader context menus (done, 1.0.9)

- Right-click on a Reservations-page row (new `reservations/_menu.html`),
  offering Diagnose/Edit/Delete/copy - the same shared `openContextMenu()`
  mechanism as leases and the subnet map, not a second implementation.
- Subnets-page rows gained a "Diagnose" inline link alongside the existing
  Map/Edit/Delete links (that page's established pattern is inline links,
  not a context menu - kept consistent rather than introducing a second
  interaction style on one page).

## Phase 3 - DHCP diagnostics (done, 1.0.9)

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

## Phase 4 - Devices workspace (done, 1.1.0)

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

## Phase 5 - Wall of Shame (done, 1.2.0)

- `wall_of_shame.py`: top-10 lists (DHCPNAKs, real IP changes, abandoned
  addresses) computed directly from `leases.py`/`diagnostics/dhcp_log.py`
  data already parsed elsewhere - three small functions, no new event
  store, no scoring. See `DECISIONS.md` for the syslog-year-assumption and
  "IP change vs. renewal" definitions.
- `/diagnostics/wall-of-shame`, reachable from the Diagnostics submenu
  and the Diagnostics overview page. Reuses the Devices context menu
  (`/devices/<mac>/menu`) - no new menu code.
- "Diagnostics" became a collapsible sidebar submenu (Overview, Wall of
  Shame) using the same `nav_group()` macro Advanced Settings already
  used, factored out once a second real use existed.

## Phase 6 - safe apply, DHCP Event Log, AI assistant (done, 1.3.1)

- Apply now restarts the service, verifies it is active, and rolls back
  to the pre-change backup if it isn't; the install itself is atomic.
- DHCP Event Log page (`/diagnostics/events`) over the existing parser.
- Read-only AI assistant (floating window) backed by a local Ollama
  server, configured under Advanced Settings > AI Settings.
- Ruff lint.

## Change impact preview (done, 1.4.6)

- Preview configuration changes before applying them, including the affected
  subnets, pools, reservations, and DHCP options.
- Identify active leases that may become invalid or unreachable after the
  change.
- Show pool-capacity changes and warn about possible address exhaustion.
- Detect conflicting reservations, duplicate addresses, and other relevant
  configuration anomalies before installation.
- Define an anomaly as either a deterministic configuration inconsistency with
  concrete evidence, or a clearly labeled runtime observation requiring
  investigation; the scanner must not present heuristics as confirmed faults.
- Present a human-readable summary of the effective DHCP behavior alongside
  the existing raw configuration diff.
- Provide a change risk summary so the administrator can quickly distinguish
  harmless edits from changes requiring careful review.
- Add a post-apply confirmation period with a one-click rollback option,
  reusing the existing backup and rollback pipeline.
- Add an embedded AI-assisted anomaly review that explains findings,
  correlates leases, reservations, devices, and DHCP events, and prioritizes
  likely operational impact.
- Add an "Explain with AI" action beside each anomaly, with evidence links
  back to the relevant configuration, lease, device, or event.
- Keep deterministic anomaly rules as the source of truth: the AI may explain,
  correlate, and suggest remediation, but must not invent findings, suppress
  rule results, or apply changes automatically.
- Treat hostnames, DHCP logs, configuration comments, and other imported data
  as untrusted context, and keep the assistant read-only with bounded input
  and output sizes.
