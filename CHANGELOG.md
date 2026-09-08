# Changelog

All notable changes to this project are documented here.

## 1.1.2

### Changed
- "Global Settings" renamed to "Advanced Settings" in the sidebar, and now groups Raw Config, Service, and Backups underneath it as a collapsible submenu (auto-expanded when one of those pages is active). No route/URL changes.
- Version bumped to 1.1.2.

## 1.1.1

### Added
- Sortable Leases and Devices tables: click a column header to sort by it (ascending, then descending, then back to the default), with an arrow indicating the active column and direction. Respected by CSV export. Numeric columns (IP address) sort numerically, not lexically.

### Changed
- Page content now scales to the actual browser window width instead of being capped at a fixed 1024px, so wide tables (Devices, Leases, Audit) get the room they need instead of squeezing into a narrow column.
- The version number shown under the logo in the sidebar was removed (redundant with the About page, which already shows it plus uptime and runtime versions).
- Version bumped to 1.1.1.

## 1.1.0

### Added
- Devices (`/devices`): a device-centric workspace correlating reservations, current leases, historical lease records, and DHCP log activity into one row per MAC address - the primary identity for a device, not its current IP. Search, filter (status/reservation/lease/subnet/vendor), sort, CSV export, bulk-select, and a right-click context menu, reusing the existing search/filter/context-menu patterns rather than parallel implementations.
- Device 360 (`/devices/<mac>`): identity, current network state, reservation, full lease history (every IP a MAC has held, oldest to newest), DHCP activity timeline (from the same DHCP log diagnostics already reads), an embedded diagnostics summary linking to the full report, and related-object links (subnet map, leases, reservations) - no dead ends between SVG, device, IP, lease, subnet, pool, and diagnostics.
- "Lease IP": a device-scoped pre-action page showing the device's context, the target subnet's pool utilization, and a deterministically-suggested next free address (lowest free address in the pool) before handing off to the existing reservation form - never silently overwrites an existing reservation or a conflicting lease.
- "Delete lease record" / bulk "Delete lease records for selected": removes Sandia's copy of a device's current lease block(s) from the leases file, backed up first - the same safe file-surgery pattern as "Clean leases". This does not live-revoke a lease (there is no OMAPI/protocol channel to dhcpd in this app); if the device is still active, dhcpd will write a new record on its next renewal, and the confirmation dialog says so.
- "Open device"/"Diagnose device" wired into every existing context menu that identifies a MAC (leases, subnet map cells, reservations), the Dashboard (device count and device-problem count tiles), and global search (a "Search devices" shortcut).
- Version bumped to 1.1.0.

### Changed
- Right-click menu wording standardized to "Diagnose device" everywhere a client/lease/IP can be diagnosed (previously "Diagnose client" in some menus), matching the device-centric model.

## 1.0.9

### Added
- Diagnostics: deterministic, evidence-based health checks for the server, a subnet/pool, and a client (`/diagnostics`, `/diagnostics/server`, `/diagnostics/client`, `/subnets/<key>/diagnose`). Every result reports status (Healthy/Warning/Critical/Unknown), problem, root cause, confidence (Confirmed/Strong/Possible/Unknown), evidence, impact, and navigable next actions - never a guess presented as fact.
- Client diagnostics ("why didn't this client get an IP?") reconstructs the DHCP flow (Client -> DHCP activity -> Subnet -> Reservation -> Pool -> Address availability -> DHCP response -> Lease) from parsed config/leases and, where available, the DHCP log (`SANDIA_DHCP_LOG_PATH`, default `/var/log/syslog`) - correlating pool exhaustion, DHCPNAK/DHCPDECLINE, reservation/IP conflicts, and interface-tag mismatches into a single root cause rather than listing every symptom separately.
- Subnet/pool diagnostics detect exhaustion, high utilization, abandoned leases, duplicate/invalid reservations, overlapping or malformed pool ranges, and interface-tag mismatches.
- "Diagnose" actions added to the existing right-click context menus (leases, subnet map cells, and a new one on the Reservations list) and as buttons on the Subnets list, subnet map, and Service pages - reusing the same context-menu mechanism throughout, not a second implementation. Launching from a menu always carries the object's MAC/IP/hostname along, so the admin never re-enters it.
- Version bumped to 1.0.9.

## 1.0.8

### Added
- Subnet map (`/subnets/<key>/map`): an SVG grid, one cell per address in the subnet's pool range, color-coded free/leased/reserved/reserved+leased/denied, with a right-click context menu per address (reserve, edit reservation, deny/undeny, copy IP/MAC) and a client-side search box that highlights matching cells. Linked from the Subnets list and the Dashboard. Pools over 1024 addresses fall back to the existing utilization bar instead of rendering individually (see `docs/DECISIONS.md`).
- Reservations whose fixed address falls outside their subnet's pool range are now listed on that subnet's map page.
- Version bumped to 1.0.8.

### Changed
- The floating right-click context-menu mechanism (previously Leases-page-only) is now shared (`base.html`) so other pages can use it; the Leases page continues to work exactly as before.

## 1.0.7

### Added
- Leases page: a state filter (Active/Free/Expired/Released/Abandoned/Backup/Reset/All), defaulting to **Active** since the leases file accumulates stale history dhcpd never removes. Combines with the existing search box; respected by CSV export.
- Reservations page: a subnet filter (All subnets/Global/a specific subnet). Respected by CSV export.
- Version bumped to 1.0.7.

## 1.0.6

### Fixed
- Config validation failed with a permission error even when running as root. Root cause: the `dhcpd -t` staging file lived under `SANDIA_DATA_DIR`, outside the AppArmor profile Debian/Ubuntu ship for `dhcpd` (`/etc/apparmor.d/usr.sbin.dhcpd`), which only allows reading `/etc/dhcp/**`. AppArmor is MAC, independent of Unix permissions - root doesn't bypass it. Fix: `staging_path` is now always a sibling of `dhcpd_conf_path`, inside `/etc/dhcp/`.

### Changed
- Error toasts (e.g. failed validation) now stay open until dismissed, render wider in monospace, and have a Copy button. Success toasts unchanged.
- "About" is now a sidebar nav entry, not just the version-number link.
- Version bumped to 1.0.6.

## 1.0.5

### Added
- Optional local cache of the full IEEE OUI (MAC vendor) registry, refreshed on demand from the About page. Runs in a background thread (never blocks), falls back to the built-in list on failure. Shows fetched-at timestamp and entry count as its "version".
- Version bumped to 1.0.5.

## 1.0.4

### Added
- Subnet interface tagging (`# interface: eth2` comment, organizational only - dhcpd has no real per-subnet interface directive).
- "Clean leases" bulk action: compacts superseded lease history, backs up first.
- Reservation "Details" panel: vendor, device type, OS guess, active lease status.
- Interfaces page (`/interfaces`) to manage the real `INTERFACESv4` setting in `/etc/default/isc-dhcp-server`, with a mismatch check against subnet interface tags.
- Version bumped to 1.0.4.

### Changed
- **Security-relevant:** bootstrap admin is now always `admin`/`admin` in real mode too (previously random). Change it before exposing the app beyond localhost.

## 1.0.3

### Added
- Toast notifications for config-change results, replacing inline banners.
- Extended per-client/per-subnet DHCP options (hostname, PXE boot, lease-time overrides, free-form extra options).
- Auto-assigned device icons on reservations (printer, phone, laptop, etc.), inferred from hostname/MAC vendor.
- Bulk reservation delete.
- Global search (IP/MAC/hostname) across reservations, leases, and subnets.
- "Edit reservation" link directly from an already-reserved lease's context menu.
- Default port changed to `7001` (was `8443`).
- Modern visual redesign: logo, gradient accents, Inter typeface, hand-authored SVG icon set.
- Watermelon branding (pink/green palette, watermelon-slice logo).
- MAC vendor (OUI) lookup for leases/reservations, 40+ vendors, offline.
- CSV export for Leases and Reservations.
- Reservations page search (name/MAC/IP).
- Config diff preview before applying raw config edits.
- Color-coded subnet utilization bars and a dashboard "at risk" count.
- Login rate-limiting: 5 failed attempts locks a username out for 5 minutes.
- About page (`/about`): version, uptime, runtime versions, key config paths.
- Dummy mode bootstraps a fixed `admin`/`admin` login instead of a random password.
- Self-service password change (`/account/password`), any role.
- `sandia --set-password USERNAME` CLI flag.

### Removed
- Sudoers grant, privileged apply helper, service account, systemd unit (`deploy/`) - standalone script now; run with `sudo` when real access is needed.

### Changed
- Renamed project/app from "dhcpweb" to **Sandia** (`SANDIA_*` env vars, `/var/lib/sandia` paths).
- Dummy mode also available as `sandia --dummy`.
- Added `sandia --version`.

### Fixed
- Raw `PermissionError` traceback on startup replaced with a clear message and fix options (`--dummy`, custom `SANDIA_DATA_DIR`, or `sudo`).
- Dummy mode now defaults its own data directory to `~/.local/share/sandia-dummy` instead of still requiring `SANDIA_DATA_DIR`.
- That fallback now applies regardless of how dummy mode was enabled (CLI flag, env var, or direct `Settings(dummy_data=True)`).
- A missing binary (`dhcpd`, `systemctl`) no longer raises an unhandled `FileNotFoundError` ("Internal Server Error"); reported as a normal command failure instead.

## 0.1.0 - initial release

### Added
- `dhcpd.conf` parser/serializer: ordering-preserving, understands `subnet`/`host`/`group`/top-level parameters, round-trips everything else untouched.
- `dhcpd.leases` parser (later blocks supersede earlier ones for the same IP).
- Web UI (FastAPI + Jinja2 + HTMX + Tailwind): dashboard, global settings, subnet CRUD, reservation CRUD, lease browser with reserve/deny from a lease, raw config editor with validation, service control, timestamped backups with restore, RBAC user management, audit log.
- Config-apply pipeline: stage -> validate (`dhcpd -t`) -> backup -> install, via a sudoers-scoped root helper.
- Self-signed HTTPS by default (EC P-256 cert), disable with `SANDIA_HTTPS=0`.
- Binds to `0.0.0.0` by default.
- Dummy-data mode: synthetic config/leases, fully sandboxed, no root needed.
- `deploy/` systemd install artifacts (sudoers file, helper script, unit, README).
- Test suite covering parser round-trip, leases parser, apply pipeline, TLS, dummy mode, and the full HTTP route layer.
