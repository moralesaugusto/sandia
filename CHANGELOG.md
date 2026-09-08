# Changelog

All notable changes to this project are documented here.

## 1.0.6

### Fixed

- **Config validation failing with a permission error even when Sandia
  runs as root.** Root cause: Sandia staged the config it validates with
  `dhcpd -t` under `SANDIA_DATA_DIR` (e.g. `/var/lib/sandia/`), but the
  `isc-dhcp-server` AppArmor profile Debian/Ubuntu ship
  (`/etc/apparmor.d/usr.sbin.dhcpd`, enforced by default) only grants
  `dhcpd` read access to `/etc/dhcp/**` and a few other fixed paths -
  never `/var/lib/sandia/`. AppArmor is mandatory access control,
  independent of Unix permissions, so root does not bypass it. Confirmed
  with a live repro: `dhcpd -t` against the old staging path produced an
  `apparmor="DENIED" ... fsuid=0` kernel audit entry even when run as
  root, and validating the identical content staged next to the real
  `dhcpd.conf` succeeded. Fix: `Settings.staging_path` now always lives
  as a sibling of `dhcpd_conf_path` (inside `/etc/dhcp/` in the default
  real-mode setup) instead of under the data directory.

### Changed

- Error-kind toasts (e.g. a failed `dhcpd -t` validation) now stay open
  until dismissed, render wider and in monospace, and have a Copy button
  - the previous 5-second auto-dismiss and narrow width made multi-line
  `dhcpd -t` errors easy to miss or impossible to read in full. Success
  toasts are unchanged.
- "About" is now a regular sidebar nav entry, not just the small version
  number link under the logo.
- Version bumped to 1.0.6.

## 1.0.5

### Added

- Optional local cache of the full IEEE OUI (MAC vendor prefix) registry,
  to improve vendor identification beyond Sandia's small built-in list.
  A "Download/Update OUI database" button on the About page (operator/
  admin) fetches `standards-oui.ieee.org/oui/oui.csv` and caches it to
  `oui_cache.json` under the data directory. The refresh always runs in a
  background thread - the button click returns immediately regardless of
  how long the download takes, and a failed or not-yet-run fetch falls
  back to the built-in list unchanged, never blocking or breaking vendor
  lookups. The About page shows the cache's fetched-at timestamp and
  entry count as its "version," so it's obvious whether you're looking at
  built-in-only or a populated cache.
- Version bumped to 1.0.5.

## 1.0.4

### Added

- Subnet-to-interface tagging: subnets can now be tagged with an interface
  name (e.g. `eth2`) when creating or editing them, shown as a badge on
  the Subnets list. **Important caveat, shown in the UI too:** ISC dhcpd
  has no `interface` statement inside a `subnet` block - which physical
  interface serves a subnet is actually determined by IP addressing and
  the service's own startup configuration, not dhcpd.conf. So this is
  stored as a `# interface: eth2` comment immediately above the subnet
  (valid syntax, safely round-trips, editable/clearable from the form) -
  an organizational label for a multi-homed server, not a live directive.
  Injecting a real `interface eth2;` parameter would simply fail `dhcpd
  -t` and get rejected by the existing validate-before-apply pipeline.
- "Clean leases" on the Leases page (admin/operator): dhcpd appends a new
  lease block on every renewal rather than rewriting the old one, so the
  leases file accumulates history. This compacts it down to just the
  current block per IP, leaving every other byte in the file (header
  comments, `server-duid`, unrelated declarations, the current state of
  every lease) completely untouched, and takes a timestamped backup
  first. No-ops cleanly if there's nothing stale to remove.
- Reservation details: a "Details" icon next to every reservation (visible
  to all roles, not just admin/operator) opens a panel with everything
  Sandia knows about that host - MAC address, vendor (OUI lookup), device
  type, a best-effort OS guess, fixed IP/subnet, configured client options
  (hostname/PXE boot), and whether it currently has an active lease and
  when it expires. The OS guess is explicitly labeled as a guess, not a
  fact - there's no real client fingerprinting data available (that would
  need DHCP options the client sent, which the lease file doesn't record),
  so it's inferred from hostname keywords and MAC vendor the same way the
  device-type icon is, and says so plainly when nothing matches.
- New Interfaces page (`/interfaces`) to manage the real `INTERFACESv4`
  setting in `/etc/default/isc-dhcp-server` (path configurable via
  `SANDIA_INTERFACES_CONF`) - the setting that actually controls which
  physical interfaces `isc-dhcp-server` listens on, as opposed to the
  organizational-only subnet interface tag above. Only the `INTERFACESv4=`
  line is touched; every other line in the file is preserved exactly, and
  a timestamped backup is taken before every write. The page cross-
  references each subnet's interface tag against the interfaces dhcpd is
  actually configured to listen on, flagging any mismatch.
- Version bumped to 1.0.4.

### Changed

- **Security-relevant:** the bootstrap admin account is now always
  `admin` / `admin`, in real mode as well as dummy mode - previously, real
  (non-dummy) mode generated a random password on first run. This is a
  known, intentional weakening for convenience; the app now prints a
  louder startup warning telling you to change it, and every existing way
  to do so (UI "Change password" link, admin User edit, `--set-password`)
  still applies. **Change the default password before exposing the app
  beyond your own machine** - it binds to `0.0.0.0` by default and a
  well-known credential is trivially guessable.

## 1.0.3

### Added

- Toast notifications: config-change results (create/update/delete/apply/
  restart/etc.) now surface as auto-dismissing corner toasts instead of an
  inline page banner, colored by success/error, with a manual dismiss and
  a 5s auto-fade. Built with safe DOM text insertion (no `innerHTML`), so
  arbitrary command output in an error toast can't execute as script.
- Extended per-client and per-subnet DHCP options, Webmin-style: a
  "Client options" section on both the reservation and subnet forms adds
  structured fields for client hostname (`option host-name`), PXE boot
  (`next-server`/`filename`), and per-subnet lease-time overrides, plus a
  free-form "extra options" textarea (one dhcpd statement per line) for
  anything not modeled explicitly. Fields are additive/removable - clearing
  one on save removes it from the config rather than leaving it stale.
- Reservations now show an automatically-assigned device icon (printer,
  phone, laptop, TV, camera, server, IoT chip, network gear, game console,
  or generic) inferred from the hostname and MAC vendor - no manual
  tagging needed.
- Bulk actions on Reservations: select-all/individual checkboxes plus a
  "Delete selected" action, in addition to per-row delete.
- Global search: a search box in the sidebar (present on every page)
  live-matches IP/MAC/hostname across reservations, leases, and subnets,
  with a dropdown of results linking straight to the relevant page.
- An already-reserved lease's context menu now links directly to editing
  that reservation ("Edit reservation ...") instead of just saying
  "Already reserved" - closes the loop on discovering *and* modifying the
  static entry behind an active lease.
- Default port changed to `7001` (was `8443`).
- Modern visual redesign: a logo mark (favicon + sidebar + login page),
  gradient accents on primary actions and the active nav item, Inter
  typeface, and general spacing/polish pass. A hand-authored inline SVG
  icon set (no external icon font/dependency) is used throughout: every
  sidebar item, every primary action button (New subnet/reservation/user,
  Edit, Delete, Save, Export CSV, Validate, Show diff, Apply, Restart,
  Enable/Disable, Restore), the dashboard stat tiles, the lease context
  menu, search inputs, and empty states.
- Watermelon branding: "Sandía" is Spanish for watermelon, so the logo is
  a watermelon-slice mark (rind/pith/flesh/seeds) and the accent palette
  moved from blue/indigo to pink and green throughout - primary buttons,
  the active nav item, links, focus rings, avatars, and the "healthy"
  utilization color (green, replacing blue - also a clearer
  green/amber/red progression). The login page has a small tagline and a
  softened pink radial glow to match.
- MAC vendor lookup: leases and reservations show the manufacturer for
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
- Subnet utilization bars are color-coded (green / amber at 70% / red at
  90%+), and the dashboard shows a "subnets at risk" count.
- Login rate-limiting: 5 failed attempts for the same username locks it
  out for 5 minutes (in-memory, per-process - this is a standalone app,
  not a multi-instance service).
- About page (`/about`, linked from the version number in the sidebar and
  login page) showing version, uptime, Python/FastAPI/Uvicorn versions,
  and key configuration paths.
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
  `/var/lib/sandia` etc.). The web UI title and browser tab now show
  "Sandia" along with the running version.
- Dummy mode is now also available as a CLI flag, `sandia --dummy`
  (equivalent to `SANDIA_DUMMY_DATA=1`), instead of only an environment
  variable.
- Added `sandia --version` to print the installed version and exit; the
  version (read from the package's own metadata, so it never drifts from
  `pyproject.toml`) is also shown in the UI sidebar and login page.

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
