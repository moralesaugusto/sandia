# Current State

Snapshot as of 1.4.6 (2026-09-30). See
`INSTRUCTIONS.md` for full user-facing docs, `CHANGELOG.md` for release history
and `SECURITY_STATUS.md` for open security findings.

## Stack

FastAPI + Jinja2 (server-rendered) + htmx for partial updates + Tailwind (play CDN,
no build step) + hand-authored inline SVG icons. SQLModel/SQLite for users, audit
log. No frontend build pipeline, no SPA framework - this is intentional and works
well for the app's size (about 7,300 lines of Python including the Spanish
catalog, and 2,500 lines of templates, measured 2026-09-30).

## Implemented

- Kea DHCPv4 (default, supported): `kea-dhcp4.conf` projected into the
  config model and patched back with only the changed values (comments and
  unmodeled keys kept), memfile lease CSV, Kea log (journal or file),
  control socket (`config-reload`, `lease4-del`), Deny via the DROP class.
- Legacy ISC: `dhcpd.conf` parsing/serialization (order-preserving),
  `dhcpd.leases`, syslog, `INTERFACESv4`.
- Full config safety pipeline: edit -> validate (`kea-dhcp4 -t`) -> diff ->
  apply (backup, atomic install, reload/restart, verify active, automatic
  rollback if the service doesn't come up) -> restore from any backup.
- Leases: parse, search, state filter, CSV export, "Clean leases" dedup (ISC only),
  right-click context menu (reserve / deny / edit reservation / copy MAC).
- Reservations: CRUD, search, subnet filter, bulk delete, CSV export, a
  "Details" modal (vendor, device-type icon, OS guess, active-lease status).
- Subnets: CRUD, a utilization bar per subnet on the list, a per-address SVG
  map over every pool (below), interface tagging (Kea's subnet `interface`).
- Interfaces page: manages Kea's `interfaces-config` (ISC: `INTERFACESv4`), cross-references
  subnet interface tags against it.
- Auth/RBAC (admin/operator/viewer), audit log, login rate-limiting, self-signed
  HTTPS, CSRF tokens on every state-changing request, a random first-run
  admin password, OUI vendor DB (built-in + optional downloaded cache).
- Subnet map (`/subnets/<key>/map`): SVG per-address grid with a shared,
  reusable right-click context-menu mechanism (`openContextMenu()` in
  `base.html`), used by leases, the map, and reservations.
- Diagnostics (`/diagnostics`, `diagnostics/`): deterministic server,
  subnet/pool, and client health checks, correlating config/leases with a
  best-effort DHCP syslog parser. Wired into every relevant context menu.
- Devices (`/devices`, `devices.py`): a device-centric view over the same
  canonical data (reservations + current leases + full lease history +
  DHCP log), keyed by MAC. Search/filter/sort/export/bulk-select, a Device
  360 detail page (identity, network state, reservation, lease history,
  DHCP activity, embedded diagnostics, related links), and a "Lease IP"
  pre-action page that suggests the next free address before handing off
  to the existing reservation form.
- Wall of Shame (`/diagnostics/wall-of-shame`, `wall_of_shame.py`, a
  Diagnostics submenu): top-10 DHCPNAK/IP-change/abandoned-lease lists,
  three time ranges, pure aggregation over existing leases/log data.
- Light/dark mode: a toggle in the sidebar (and on the login page). Saved
  in the session immediately and, for a logged-in user, on their account
  (`User.theme`) so it follows them across browsers/devices.
- DHCP Event Log (`/diagnostics/events`): the parsed DHCP log as a
  filterable/searchable table, newest first, capped at 500 rows.
- AI assistant (`ai.py`, `routers/ai.py`): a floating chat window in
  `base.html` backed by a local Ollama server configured in Advanced
  Settings > AI Settings (`AiSettings` table). Read-only, answers from a
  server-built snapshot of config/leases/log/service status.
- Change review (1.4.6, `pending_changes.py`, `change_impact.py`,
  `routers/review.py`): every config edit is staged and shown on a Review
  page (risk, effective behavior, changes, affected leases, capacity,
  anomalies, diff) before Apply; a 10-minute Keep/Roll back banner
  (`rollback_window.py`) follows each apply. `/diagnostics/anomalies` scans
  the live config with the same rules (`diagnostics.scan_config`). The AI
  assistant can explain a pending change's findings ("Explain with AI",
  "Review with AI") but never changes them.
- Ruff lint configured (`uv run ruff check .`).
- English/Spanish UI (`i18n.py`, catalog in `i18n_es.py`): selector in the
  top-right corner, saved per session and per account (`User.language`).
- pytest suite: 409 tests, all passing on 2026-09-30.

## What existed at the first commit versus what was built since

From git history: the initial commit (`78dde6b`, 2026-09-05) already
contained a working app (pyproject version 0.1.0, with unreleased changes that
shipped as 1.0.3 in the next commits). It had config editing with
validate/diff/backup/apply, leases with a right-click menu (the only context
menu at the time), reservations, subnets with utilization bars, auth/RBAC,
the audit log and HTTPS. The current `CLAUDE.md`, which describes an
SVG-based subnet map, broad context menus and troubleshooting as existing
features, was added in `ce90d50` (2026-09-08), the same commit that built
the SVG map. The features it describes were built after that:

- SVG subnet map and shared context menus: 1.0.8.
- Diagnostics and context menus on reservations: 1.0.9.
- Devices workspace: 1.1.0.
- Wall of Shame: 1.2.0.
- Light/dark mode: 1.3.0.
- Apply with rollback, DHCP Event Log, AI assistant: 1.3.1.
- English/Spanish UI: 1.4.0.
- Kea DHCPv4 is the default and only supported backend, with full feature parity: 1.4.5. isc-dhcp-server remains selectable (`SANDIA_DHCP_BACKEND=isc`) but unsupported.

## Not yet implemented (from the product-direction wishlist)

Operational alerts/paging,
a server health page beyond `/diagnostics/server`, live/real-time updates.
See `ROADMAP.md`. Open security findings are tracked in `SECURITY_STATUS.md`.
