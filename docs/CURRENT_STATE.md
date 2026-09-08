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
  (backup then install) -> restore from any backup. Already matches the
  "Configuration Safety" product-direction goal in full.
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
- 147 tests, all passing as of the start of this pass.

## Gap identified at the start of this pass

Project instructions describe an "SVG-based subnet/IP visualization" and
broad multi-object right-click context menus as existing core features to be
preserved. Neither existed in the codebase: subnet utilization was a single
bar (no per-IP visual), and the only working right-click context menu was on
the Leases table. This was verified by reading every template and router, not
assumed from the instructions.

This pass adds the SVG per-IP subnet map as a new first-class surface (see
`ROADMAP.md`) rather than "preserving" something that wasn't there, and
generalizes the existing lease context-menu JS so new surfaces can reuse it.

## Not yet implemented (from the product-direction wishlist)

DHCP troubleshooting view, DHCP event log, operational alerts, server health
page, live/real-time updates, conflict detection beyond `dhcpd -t` validation.
See `ROADMAP.md`.
