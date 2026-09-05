# Changelog

All notable changes to this project are documented here.

## Unreleased

### Added

- Default port changed to `7001` (was `8443`).
- Modern visual redesign: a logo mark (favicon + sidebar + login page),
  an icon for every sidebar item, gradient accents on primary actions and
  the active nav item, Inter typeface, and general spacing/polish pass.
- MAC vendor lookup: leases and reservations now show the manufacturer for
  recognized MAC address prefixes (Apple, Samsung, Raspberry Pi Foundation,
  Ubiquiti, TP-Link, Espressif, and 40+ others), via a small self-contained
  OUI table - no network calls.
- CSV export for both the Leases and Reservations pages (respects the
  current search filter).
- Reservations page now has search (by name/MAC/IP), matching the Leases
  page.
- Config diff preview on the Raw Config page: "Show diff" renders a
  unified diff between the live config and the staged edit before you
  apply it.
- Subnet utilization bars are now color-coded (green / amber at 70% /
  red at 90%+), and the dashboard shows a "subnets at risk" count.
- Login rate-limiting: 5 failed attempts for the same username locks it
  out for 5 minutes (in-memory, per-process - this is a standalone app,
  not a multi-instance service).
- About page (`/about`, linked from the version number in the sidebar and
  login page) showing version, uptime, Python/FastAPI/Uvicorn versions,
  and key configuration paths.

### Removed

- The sudoers grant, privileged apply helper script, dedicated service
  account, and systemd unit (`deploy/`) - this is a standalone script, not
  a system service. Real config apply now writes directly to
  `/etc/dhcp/dhcpd.conf` (after validating and backing it up) and calls
  `systemctl` directly for service control; run the app with `sudo` when
  it needs that access, and as yourself otherwise (day-to-day use, dummy
  mode). Removed the `SANDIA_USE_SUDO`/`SANDIA_APPLY_HELPER` settings along
  with it.

### Changed

- Renamed the project and web app from "dhcpweb" to **Sandia** (package
  `sandia`, console command `sandia`, all `DHCPWEB_*` environment variables
  renamed to `SANDIA_*`, default paths moved from `/var/lib/dhcpweb` etc. to
  `/var/lib/sandia` etc., systemd unit/service account/deploy scripts
  renamed to match). The web UI title and browser tab now show "Sandia"
  along with the running version.
- Dummy mode is now also available as a CLI flag, `sandia --dummy`
  (equivalent to `SANDIA_DUMMY_DATA=1`), instead of only an environment
  variable.
- Added `sandia --version` to print the installed version and exit; the
  version (read from the package's own metadata, so it never drifts from
  `pyproject.toml`) is also shown in the UI sidebar and login page.

- Dummy mode now bootstraps a fixed, well-known testing login (`admin` /
  `admin`) instead of a random password, so there's nothing to copy from
  stdout before trying the UI. Real (non-dummy) mode is unaffected and
  still generates a random admin password on first run.
- Self-service password change: any logged-in user (any role) can change
  their own password from a "Change password" link in the sidebar
  (`/account/password`), given their current password.
- `sandia --set-password USERNAME`: set any user's password from the
  command line (prompts for it, doesn't start the server) - useful to
  change the dummy-mode default or recover access without going through
  the UI.

### Fixed

- `uv run sandia` (and dummy mode) crashed with a raw `PermissionError`
  traceback when the default system paths (`/var/lib/sandia`, `/etc/dhcp/
  dhcpd.conf`, ...) weren't writable by the current user - which is the
  case for any non-root account. The app now prints a clear message naming
  the exact path that failed and the three ways to fix it (`--dummy`, a
  custom `SANDIA_DATA_DIR`, or running with `sudo`), and exits cleanly
  instead.
- Dummy mode sandboxed the dhcpd config/leases/backup paths but not the
  app's own data directory, so it still hit the `/var/lib/sandia`
  permission error unless `SANDIA_DATA_DIR` was *also* set by hand -
  contradicting its "no special access needed" premise. It now defaults
  its own data directory to a per-user location
  (`~/.local/share/sandia-dummy`) automatically when enabled, unless
  `SANDIA_DATA_DIR` is explicitly set.
- The above fallback only applied when dummy mode was reached through the
  CLI flag or environment variable; constructing `Settings(dummy_data=True)`
  directly still fell back to `/var/lib/sandia` and hit the same permission
  error. `data_dir` resolution is now unified in one place so both paths
  behave the same.
- Calling a missing binary (`dhcpd`, `systemctl`) raised an unhandled
  `FileNotFoundError` that surfaced as a bare "Internal Server Error" to
  the browser. It's now reported the same way as any other command
  failure (a flash message and an audit log entry), without touching the
  live config.

## 0.1.0 - initial release

### Added

- `dhcpd.conf` parser and serializer: a scoped, ordering-preserving parser
  for ISC dhcpd's config DSL. Structurally understands `subnet`, `host`,
  `group`, and top-level parameters/options; anything else (`shared-network`,
  `class`, `key`, failover peers, ...) round-trips byte-for-byte untouched.
- `dhcpd.leases` parser for lease monitoring (later blocks for the same IP
  correctly supersede earlier ones).
- Web UI (FastAPI + Jinja2 + HTMX + Tailwind, no Node build step):
  - Dashboard with service status, subnet utilization, recent activity.
  - Global settings editor (authoritative, lease times, DNS/domain options).
  - Subnet (scope) create/edit/delete.
  - Static reservation create/edit/delete, with subnet assignment.
  - Lease browser with search/filter and a right-click menu to reserve or
    deny a client directly from an observed lease.
  - Raw config editor with live validation before apply.
  - Service control: restart, enable/disable at boot, live status polling.
  - Timestamped config backups with one-click restore.
  - User management with role-based access control (admin / operator /
    viewer) and an audit log of every change.
- Config-apply pipeline: stage -> validate (`dhcpd -t`) -> backup -> install,
  via a narrowly-scoped root helper script invoked through a dedicated
  sudoers grant - the app itself never runs as root and never writes
  `/etc/dhcp/dhcpd.conf` directly.
- Self-signed HTTPS by default, using an elliptic-curve (P-256) certificate
  generated automatically on first run and reused thereafter; HTTPS can be
  disabled with `SANDIA_HTTPS=0` (e.g. behind a reverse proxy).
- Binds to `0.0.0.0` by default (reachable from other machines, not just
  localhost).
- Dummy-data mode, for exploring the UI without a real `isc-dhcp-server`,
  root access, or sudo: seeds a synthetic `dhcpd.conf`/`dhcpd.leases`,
  sandboxes all file paths under the data directory, and simulates the
  apply/service-control pipeline in-process.
- `deploy/` artifacts for a production systemd install: sudoers file,
  privileged apply helper, systemd unit, and a provisioning README.
- Test suite (`uv run pytest`) covering the parser/serializer round-trip,
  the leases parser, the apply pipeline, TLS certificate generation, dummy
  mode, and the full HTTP route layer (auth, RBAC, CRUD flows).
