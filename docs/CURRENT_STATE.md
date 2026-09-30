# Current State

Snapshot as of this modernization pass. See `INSTRUCTIONS.md` for full user-facing
docs and `CHANGELOG.md` for release history.

## Stack

FastAPI + Jinja2 (server-rendered) + htmx for partial updates + Tailwind (play CDN,
no build step) + hand-authored inline SVG icons. SQLModel/SQLite for users, audit
log. No frontend build pipeline, no SPA framework - this is intentional and works
well for the app's size (~3,500 lines Python, ~1,200 lines templates).

## Implemented

- `dhcpd.conf` parsing/serialization (order-preserving), subnets, host
  reservations (nested or top-level), groups, extra/free-form options.
- Full config safety pipeline: edit -> validate (`dhcpd -t`) -> diff -> apply
  (backup, atomic install, restart, verify active, automatic rollback if
  the service doesn't come up) -> restore from any backup.
- Leases: parse, search, state filter, CSV export, "Clean leases" dedup,
  right-click context menu (reserve / deny / edit reservation / copy MAC).
- Reservations: CRUD, search, subnet filter, bulk delete, CSV export, a
  "Details" modal (vendor, device-type icon, OS guess, active-lease status).
- Subnets: CRUD, per-subnet utilization bar (text/bar based, not visual grid),
  interface tagging (`# interface: eth2` comment convention).
- Interfaces page: manages the real `INTERFACESv4` setting, cross-references
  subnet interface tags against it.
- Auth/RBAC (admin/operator/viewer), audit log, login rate-limiting, self-signed
  HTTPS, OUI vendor DB (built-in + optional downloaded cache).
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
- Ruff lint configured (`uv run ruff check .`).
- English/Spanish UI (`i18n.py`, catalog in `i18n_es.py`): selector in the
  top-right corner, saved per session and per account (`User.language`).
- 398 tests, all passing as of the end of this pass.

## Gaps identified and closed across recent passes

Project instructions describe an "SVG-based subnet/IP visualization",
broad multi-object right-click context menus, and DHCP diagnostics as
existing core features to preserve. At the start none of them existed:
subnet utilization was a single bar, the only context menu was on Leases,
and there was no correlation of config/leases/logs into a diagnosis. Each
was verified against the actual codebase (grep, reading every template and
router) before being built, rather than assumed from the instructions. Both
gaps are now closed - see `ROADMAP.md` Phases 1-3.

## Not yet implemented (from the product-direction wishlist)

Operational alerts/paging,
a server health page beyond `/diagnostics/server`, live/real-time updates.
See `ROADMAP.md`.
