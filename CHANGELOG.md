# Changelog

All notable changes to this project are documented here.

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
