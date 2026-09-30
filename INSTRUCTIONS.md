# Instructions

## What this is

Sandia is a web UI for managing an ISC `isc-dhcp-server` instance:

- Edit `dhcpd.conf` - global settings, subnets/scopes (optionally tagged
  with an interface name for your own organization - see "Subnet
  interface tags" below), static reservations (including Webmin-style
  client options: hostname, PXE boot server/file, lease-time overrides,
  and a free-form "extra options" field for anything else), or the raw
  file directly (with a diff preview before applying).
- Browse and search leases, with MAC vendor identification, CSV export,
  a right-click menu to reserve or deny a client from an observed lease
  (or jump straight to editing the reservation if it's already reserved),
  and a "Clean leases" action to compact out stale renewal history. A
  state filter (Active/Free/Expired/.../All) defaults to **Active**, since
  the leases file accumulates stale history dhcpd never removes.
- A "Details" panel on every reservation showing everything Sandia knows
  about that host: vendor, device type, a best-effort OS guess, client
  options, and whether it currently has an active lease. A subnet filter
  (All/Global/a specific subnet) narrows the list down.
- A global search box (in the sidebar, on every page) that matches IP,
  MAC, or hostname across reservations, leases, and subnets at once.
- A subnet map (`/subnets/<key>/map`, linked from the Subnets list and
  Dashboard): an SVG grid, one cell per address in the subnet's pool range,
  color-coded free/dynamically-leased/reserved/reserved-and-leased/denied,
  with a right-click menu per address (reserve, edit reservation, deny/undeny
  a client, copy IP/MAC) and a search box that highlights matching cells.
  Reservations outside the pool range are listed separately below the grid.
  Pools over 1024 addresses are too large to render individually and fall
  back to the existing utilization bar.
- Devices (`/devices`): a device-centric workspace - every DHCP client,
  keyed by MAC (not just its current IP), correlated from reservations,
  current leases, historical lease records, and DHCP log activity. Search,
  filter (status/reservation/lease/subnet/vendor), sort, CSV export, and
  bulk-select. Clicking a device opens Device 360 (`/devices/<mac>`):
  identity, current network state, reservation, full lease history (every
  IP it has held), a DHCP activity timeline, an embedded diagnostics
  summary, and related links (subnet map, leases, reservations). "Lease
  IP" shows the device's context and a deterministically-suggested next
  free address before handing off to the reservation form - it never
  overwrites an existing reservation. "Delete lease record" removes
  Sandia's copy of a device's current lease from the leases file (backed
  up first) - it does not live-revoke a lease dhcpd is still serving.
- Diagnostics (`/diagnostics`): deterministic, evidence-based health checks
  for the server, a subnet/pool, or a client - "why didn't this client get
  an IP?" reconstructs the DHCP flow (client, DHCP log activity, subnet,
  reservation, pool, address availability, DHCP response, lease) from
  parsed config/leases and, where readable, the DHCP log
  (`SANDIA_DHCP_LOG_PATH`, default `/var/log/syslog`). Every result reports
  status, root cause, confidence, evidence, impact, and next actions - if
  the evidence doesn't support a conclusion, it says so explicitly rather
  than guessing. Reachable from the sidebar, or via a "Diagnose" action in
  the leases/subnet-map/reservations context menus and the Service page,
  which carries the object's MAC/IP/hostname along automatically. The
  Diagnostics sidebar entry is a submenu (Overview, Event Log, Wall of Shame).
- Event Log (`/diagnostics/events`): every dhcpd line parsed from the tail
  of the DHCP log, newest first, filterable by event type
  (DHCPDISCOVER/OFFER/REQUEST/ACK/NAK/DECLINE/RELEASE/INFORM or other
  dhcpd messages) and searchable by IP, MAC, hostname or message text.
  Shows the newest 500 matches; right-click a row with a MAC for the
  Devices context menu. Events are not stored in a database - they're
  parsed from the last 2 MB of the log on each request, so history ends
  where that window or log rotation does (explained on the About page).
- Wall of Shame (`/diagnostics/wall-of-shame`): the top 10 devices by
  DHCPNAK count, the top 10 by real IP-address changes (lease renewals of
  the same address don't count), and the top 10 abandoned-lease addresses
  (shown as a bare IP, never a guessed device, when dhcpd didn't record a
  MAC for that abandonment) - three time ranges (last 24 hours, last 7
  days, all available; defaults to 24 hours). A plain count of existing
  leases/DHCP-log data, no scoring or inference. Right-click reuses the
  Devices context menu.
- An Interfaces page to manage the real `INTERFACESv4` setting (which
  physical interfaces `isc-dhcp-server` actually listens on) - see
  "Interfaces page" below.
- An optional local cache of the full IEEE OUI (MAC vendor) registry,
  refreshed on demand from the About page, to improve vendor
  identification beyond the small built-in list - see "OUI vendor
  database" below.
- Bulk-select and delete reservations, in addition to one at a time.
- Restart/enable/disable/check the `isc-dhcp-server` service.
- Back up and restore config, with a diff shown before any apply.
- Manage users with role-based access (admin / operator / viewer),
  audit logging, and login rate-limiting.
- Toast notifications for every config change, success or failure.
- AI assistant: a floating chat window (bottom-right button, draggable)
  that answers questions about the DHCP config, leases and log using a
  local [Ollama](https://ollama.com) server. It is read-only - it never
  changes anything. An admin sets the Ollama server address (an IP or
  hostname defaults to `http://<host>:11434`) and model under Advanced
  Settings > AI Settings ("Load models" lists what the server has
  installed); the button appears only once both are set. Every question
  sends a snapshot of the service status, `dhcpd.conf`, active leases and
  the last 150 DHCP log lines to that server, so point it only at an
  Ollama instance you trust with that data.
- English/Spanish UI: the EN | ES switch in the top-right corner (also on
  the login page). English is the default; the choice is saved on your
  account. Acronyms, config keywords and the terms lease, subnet, pool,
  host and gateway stay in English in the Spanish UI.
- Light/dark mode toggle (sidebar, and on the login page). Saved
  immediately in the browser session, and on the account once logged in,
  so it follows you to a new browser or device.

All config changes go through the same path: stage the new config,
validate it (`dhcpd -t`), back up the live file, install it atomically,
restart `isc-dhcp-server` and check it is running. If the service does not
come back up, the previous config is restored and the service restarted on
it - so a bad edit never leaves the server down.

It's a plain standalone script, not a system service: there's no dedicated
service account, no sudoers setup, no systemd unit. Run it as yourself for
everyday use or dummy mode; run it with `sudo` when it needs to touch real
system files (`/etc/dhcp/dhcpd.conf`) or control the `isc-dhcp-server`
service.

## Prerequisites

- Python 3.13+ and [`uv`](https://docs.astral.sh/uv/) installed.
- For real (not just dummy-data) use: `isc-dhcp-server` installed
  (`sudo apt-get install isc-dhcp-server`). The app itself does not require
  this to start - it will simply show an empty config until one exists.

## Running it

From the project directory:

```
uv sync
uv run sandia
```

**Note:** the default paths (`/var/lib/sandia`, `/etc/dhcp/dhcpd.conf`,
`/var/backups/sandia`) need root to write. Running the bare command above
as your own user will fail with a permission error unless you're root. If
you just want to try it out locally, either:

```
uv run sandia --dummy        # no privileges needed at all
```

or point it at somewhere you can write:

```
SANDIA_DATA_DIR=$HOME/.local/share/sandia uv run sandia
```

or, to manage a real `dhcpd.conf` and control the real service, run it
with sudo (after `uv sync`, so `.venv` already exists - `sudo` resets your
shell environment, so invoke the venv's binary directly rather than
`sudo uv run sandia`):

```
sudo .venv/bin/sandia
```

If you do hit a permission error, the app prints which path failed and
which of the above to do about it, instead of a raw traceback.

**If a config change fails validation with a permission error even though
Sandia is running as root**: that's AppArmor, not a Unix permissions bug.
Debian/Ubuntu's `isc-dhcp-server` package ships an enforced-by-default
AppArmor profile (`/etc/apparmor.d/usr.sbin.dhcpd`) that only grants
`dhcpd` read access to `/etc/dhcp/**` and a handful of other fixed paths.
AppArmor is mandatory access control on top of, and independent from,
Unix permissions - root does not bypass it for a confined binary. Sandia
stages the config it validates with `dhcpd -t` right next to the real
`dhcpd.conf` (inside `/etc/dhcp/`, which the stock profile already
allows) specifically to avoid this. If you've relocated `DHCPD_CONF_PATH`
somewhere AppArmor doesn't cover, or you're seeing `apparmor="DENIED"`
entries in `dmesg`/`journalctl -k` mentioning `dhcpd`, either move
`DHCPD_CONF_PATH` back under `/etc/dhcp/`, or add the directory to a
local AppArmor override at `/etc/apparmor.d/local/usr.sbin.dhcpd`
(supported by the stock profile) and reload with `sudo systemctl reload
apparmor`.

This starts the server bound to `0.0.0.0` (reachable from other machines on
the network, not just localhost). On first startup it also:

- Creates `sandia.db` (SQLite) with a default `admin` / `admin` login, in
  every mode (real or dummy), and prints a security warning to stdout
  telling you to change it. **Change this immediately if the app is
  reachable from anywhere but your own machine** - see "Changing a
  password" below.
- Generates a self-signed HTTPS certificate (elliptic-curve, P-256) if HTTPS
  is enabled and no certificate exists yet at `<data dir>/tls/` (see below).
  If a certificate is already there, it's reused as-is; if it's ever deleted
  or only half-present, a fresh one is generated automatically on the next
  start - you never have to do this by hand.

Then open the URL it prints (`https://<host>:<port>/login` by default) and
log in with `admin` and the printed password. Your browser will warn that
the certificate is self-signed/untrusted - that's expected for a self-hosted
tool; accept it (or import the cert - see "HTTPS" below) to proceed.

## Command-line flags

```
uv run sandia --help
```

- `--dummy` - run with synthetic demo data, no privileges needed. Equivalent
  to setting `SANDIA_DUMMY_DATA=1`. See "Trying it with dummy data" below.
- `--set-password USERNAME` - set an existing user's password from the
  command line (prompts for it, doesn't start the server) - see "Changing
  a password" below.
- `--version` - print the installed version and exit.

## Configuration (environment variables)

All optional; defaults match a standard Debian `isc-dhcp-server` install.

| Variable | Default | Meaning |
|---|---|---|
| `SANDIA_HOST` | `0.0.0.0` | Interface to bind. `0.0.0.0` means "all interfaces" - reachable from other machines, not just `localhost`. |
| `SANDIA_PORT` | `7001` | Port to listen on. |
| `SANDIA_HTTPS` | `1` (enabled) | Set to `0` to serve plain HTTP instead of HTTPS - see below. |
| `DHCPD_CONF_PATH` | `/etc/dhcp/dhcpd.conf` | The live dhcpd config file this app edits. |
| `DHCPD_LEASES_PATH` | `/var/lib/dhcp/dhcpd.leases` | Lease database read for the Leases page. |
| `SANDIA_INTERFACES_CONF` | `/etc/default/isc-dhcp-server` | The `INTERFACESv4` defaults file, managed from the Interfaces page. |
| `SANDIA_DATA_DIR` | `/var/lib/sandia` | Where the app keeps its own state: SQLite DB, staged config drafts, session secret, and the TLS cert/key (under `tls/`). |
| `SANDIA_BACKUP_DIR` | `/var/backups/sandia` | Timestamped `dhcpd.conf` backups, one taken automatically before every applied change. |
| `SANDIA_SERVICE_NAME` | `isc-dhcp-server` | systemd unit name used for restart/enable/disable/status. |
| `SANDIA_DUMMY_DATA` | `0` (disabled) | Same as `--dummy` - set to `1` to explore the UI with synthetic data. **Testing only.** |

## How real config changes and service control work

No sudoers file, no privileged helper script, no service account - the app
just does the work directly, so it needs to actually be running with
enough privilege at the time:

- **Applying a config change**: writes the new config to a staging file,
  runs `dhcpd -t -cf <staging file>` to validate it, backs up the current
  `/etc/dhcp/dhcpd.conf` with a timestamp, then installs the staged file
  (copied alongside and renamed over it, so a crash can't leave a
  half-written config). It then runs `systemctl restart` and
  `systemctl is-active`; if either fails, the backup just taken is put
  back and the service restarted again, and the error (plus whether the
  rollback worked) is shown. Validation only needs to read the staging
  file (usually fine without root); install and restart need write
  access to `/etc/dhcp/` and `SANDIA_BACKUP_DIR` and systemctl rights, so
  they need `sudo` in a normal install.
- **Restart/enable/disable/status**: calls `systemctl <action> isc-dhcp-server`
  directly. Restart/enable/disable need `sudo`; status usually doesn't.
- If a command isn't available or isn't permitted, the app reports the
  failure in the UI (a flash message and an audit log entry) instead of
  crashing - the live config is left untouched.

In short: run the app as yourself day-to-day (browsing leases, dummy mode,
editing config drafts), and re-run it with `sudo` for the session where you
actually want to apply that config or restart the service.

## Subnet interface tags

Subnets can be tagged with an interface name (e.g. `eth2`) from the
subnet form. **This is organizational metadata, not a live directive**:
ISC dhcpd has no `interface` statement inside a `subnet` block - which
physical interface actually serves a subnet is determined by IP
addressing and how the `isc-dhcp-server` service itself is started
(`INTERFACESv4` in `/etc/default/isc-dhcp-server`), not by anything in
`dhcpd.conf`. Trying to make it a real directive (`interface eth2;` inside
the subnet) would simply fail `dhcpd -t` and get rejected before it ever
reached the live file.

So the tag is stored as a `# interface: eth2` comment immediately above
the subnet's declaration - valid syntax dhcpd ignores, that round-trips
safely and is editable/clearable from the form. It's there to help you
keep track of which subnet belongs to which physical interface on a
multi-homed server; it doesn't change dhcpd's actual behavior.

## Interfaces page (the real `INTERFACESv4` mechanism)

The Interfaces page (`/interfaces`) edits the actual setting that
controls which physical interfaces `isc-dhcp-server` listens on:
`INTERFACESv4` in `SANDIA_INTERFACES_CONF` (default
`/etc/default/isc-dhcp-server`, a shell-sourced file read by the service's
init script/systemd unit at startup). Only that one line is touched -
every other line (`DHCPDv4_CONF`, `OPTIONS`, `INTERFACESv6`, comments) is
preserved exactly. A timestamped backup is taken before every write, same
as `dhcpd.conf`.

The page also cross-references each subnet's interface tag (see above)
against the interfaces actually listed here, flagging any subnet tagged
with an interface dhcpd isn't configured to listen on - a common source
of "why isn't this subnet handing out leases" confusion. Changing
`INTERFACESv4` requires restarting `isc-dhcp-server` to take effect (the
service does not pick it up live).

## OUI vendor database

Sandia ships a small built-in list of common MAC vendor prefixes (~100
entries) used for vendor identification on the Leases/Reservations pages,
which works offline with zero setup. The About page (`/about`) has a
"Download OUI database" / "Update OUI database" button (operator/admin)
that fetches the full public IEEE OUI registry
(`https://standards-oui.ieee.org/oui/oui.csv`, tens of thousands of
entries) and caches it locally as `oui_cache.json` under
`SANDIA_DATA_DIR`.

- **Non-blocking**: the download runs in a background thread. The button
  click returns immediately with a "refresh started" message; reload the
  About page to see progress or the result.
- **Never required**: if the fetch fails (no internet access, IEEE
  unreachable) or hasn't been run yet, the built-in list keeps working
  exactly as before - this is a pure enhancement, not a dependency.
- **Version shown**: the About page shows when the cache was last fetched
  and how many entries it holds, so you can tell built-in-only apart from
  a populated cache at a glance.
- The built-in list is always checked first (it has some friendlier,
  curated names for common devices); the downloaded cache is only
  consulted for prefixes the built-in list doesn't recognize.

## Cleaning the leases file

dhcpd appends a new `lease <ip> { ... }` block to `dhcpd.leases` on every
renewal instead of rewriting the old one in place, so a long-running
server accumulates history. "Clean leases" on the Leases page (admin/
operator) keeps only the current block per IP and removes the rest -
every other byte in the file (header comments, `server-duid`, anything
else it doesn't need to touch, and the current state of every lease) is
left completely alone, and a timestamped backup is taken first. It's a
no-op if there's nothing stale to remove.

## Trying it with dummy data (no real dhcpd, no root/sudo needed)

To just look at and click through the UI - without installing
`isc-dhcp-server`, without root, without `sudo`:

```
uv run sandia --dummy
```

This is for testing/demo purposes only, not a substitute for the real
thing. When enabled, the app:

- Defaults its own data directory to `~/.local/share/sandia-dummy` (instead
  of `/var/lib/sandia`, which needs root) unless you set `SANDIA_DATA_DIR`
  yourself.
- Seeds a synthetic `dhcpd.conf` (two subnets, a handful of reservations)
  and `dhcpd.leases` (a mix of active/free leases) under
  `<SANDIA_DATA_DIR>/dummy/` - never at `/etc/dhcp/...` or any path you
  passed via `DHCPD_CONF_PATH`/`DHCPD_LEASES_PATH`, so it can never
  overwrite a real config by accident. Seeding only happens if those files
  don't already exist yet, so edits you make through the UI in one session
  are still there the next time you start it.
- "Apply" writes straight to the sandboxed dummy config file (still taking
  a timestamped backup first), and service restart/enable/disable/status
  are simulated in-process instead of calling `systemctl` - none of it
  needs `dhcpd` or `isc-dhcp-server` to actually be installed.
- Everything else - auth, RBAC, the parser, the leases page, backups,
  audit log - behaves exactly as it would against a real config.

This is also the fastest way to sanity-check a fresh install or a port to
another machine (see below) before wiring it up to a real `dhcpd.conf`.

## Changing a password

`admin` / `admin` is a fixed, publicly-known default password, used in
every mode (not just dummy) so there's nothing to copy off stdout before
logging in for the first time. **Change it before the app is reachable
from anywhere but your own machine** - any of these ways:

1. **In the web UI, for your own account**: once logged in, click "Change
   password" in the sidebar (or go to `/account/password`). Works for any
   role, requires your current password.
2. **In the web UI, for any account, as an admin**: Users > (pick a user) >
   Edit > enter a new password, leave it blank to keep the current one.
   This is also how an admin resets another user's forgotten password.
3. **From the command line**, without starting the server (e.g. if you're
   locked out): `sandia --set-password admin` - prompts for the new
   password twice and writes it straight to the database file at
   `<SANDIA_DATA_DIR>/sandia.db`. Needs read/write access to that file, but
   nothing else (no need to be root, no need for the server to be running).
4. **By modifying files directly (last resort)**: delete
   `<SANDIA_DATA_DIR>/sandia.db` and restart the app - this wipes *all*
   users, sessions, and the audit log and re-runs the first-run bootstrap
   (`admin` / `admin` again). Only do this when you don't need anything in
   the existing database.

## HTTPS

HTTPS is **on by default** and uses a self-signed elliptic-curve (P-256)
certificate that the app generates itself on first run - no external CA or
manual `openssl` step needed. The cert and key live at
`<SANDIA_DATA_DIR>/tls/cert.pem` and `key.pem`.

- **To make HTTPS optional / turn it off** (e.g. running behind a reverse
  proxy like nginx or Caddy that terminates TLS itself, or for quick local
  testing): set `SANDIA_HTTPS=0`. No certificate is generated in this mode
  and the app serves plain HTTP on `SANDIA_HOST:SANDIA_PORT`.
- **To force a new certificate** (e.g. after changing hostname): delete
  `<SANDIA_DATA_DIR>/tls/cert.pem` and `key.pem` and restart the app - a
  fresh pair is generated automatically. You don't need to delete both by
  hand in normal operation: if either file is missing, the app treats the
  pair as absent and regenerates both together (so you never end up with a
  mismatched cert/key).
- **To trust the certificate instead of clicking through the browser
  warning**, import `<SANDIA_DATA_DIR>/tls/cert.pem` into your OS or
  browser's trusted certificate store.

## Running the tests

```
uv run pytest
uv run ruff check .
```

380+ tests cover the `dhcpd.conf` parser/serializer (round-trip and
idempotence), the leases file parser, the stage/validate/apply pipeline,
TLS certificate generation, dummy mode, the CLI flags (including
`--set-password`), MAC vendor lookup (including the OUI cache fallback
and background refresh), device-icon/OS-guess assignment, the extra DHCP
client options round-trip, subnet interface tagging, the `INTERFACESv4`
read/write logic, the leases-cleanup dedup logic, the config diff, login
rate-limiting, global search, bulk reservation delete, the leases state
filter and reservations subnet filter, the subnet map's per-address status
logic and its context menu across every status (free, reserved, reserved
and leased, dynamically leased, denied), the diagnostics engine (DHCP log
parsing, server/subnet/pool/client checks, and the client root-cause
priority chain - including that no Critical/Warning finding is ever
reported without supporting evidence and a non-Unknown confidence), the
device inventory (discovery from active/historical leases, reservation
correlation, multi-IP history, status/problem detection, filtering, bulk
lease-record deletion, and every device/IP/subnet cross-navigation path),
the Wall of Shame (DHCPNAK/IP-change/abandoned-lease counts, time-range
filtering, and that devices with zero events never appear), the Event
Log page, the restart/verify/rollback apply stage, the AI assistant
(Ollama URL handling, context building, streaming, and that the browser
can never supply the system prompt), and the full
HTTP route layer
(login, RBAC boundaries, subnet/reservation CRUD, self-service
password change, the "reserve from lease" flow, the Interfaces page, the
OUI database refresh, and config-validation failure paths).

## Running it standalone / porting to another machine

The app has no build step, no service to install, and no external
services (SQLite is a plain file, TLS is self-generated) - everything it
needs lives in this project directory plus whatever `SANDIA_DATA_DIR`
points at. Moving it to another machine is just: copy the code, resolve
dependencies there, run it.

1. **Copy the project**, excluding the virtual environment and caches
   (`.venv` is platform-specific - a venv built on one machine/architecture
   will not work on another, so never copy it). With `tar` (no extra tools
   needed):

   ```
   tar -cf - --exclude=.venv --exclude=.git --exclude=__pycache__ \
     --exclude=.pytest_cache . | ssh user@target-host 'mkdir -p /path/to/sandia && tar -xf - -C /path/to/sandia'
   ```

   `rsync -a --exclude .venv --exclude .git --exclude __pycache__ --exclude .pytest_cache ./ user@target-host:/path/to/sandia/`
   works the same way if `rsync` is installed. A plain `scp -r` or
   `git clone`/`git archive` of the repo also works, as long as `.venv` is
   excluded - `uv.lock` is what actually matters, and it's a small text
   file that's always included.

2. **On the target machine**, install `uv` if it isn't already there
   ([docs](https://docs.astral.sh/uv/getting-started/installation/)), then:

   ```
   cd /path/to/sandia
   uv sync
   ```

   `uv sync` reads `uv.lock` and installs the exact same dependency
   versions this project was built and tested with, into a fresh `.venv`
   for that machine - no manual pip/requirements management, and no
   dependency drift between machines.

3. **Smoke-test the port** before touching anything real:

   ```
   uv run sandia --dummy
   ```

   If the dashboard loads and shows the seeded subnet/leases, the port is
   good. Then run it for real - `uv run sandia`, or `sudo .venv/bin/sandia`
   once you're ready to point it at a real `dhcpd.conf` and restart the
   real service.

4. **State that does *not* travel with the code**, and is specific to each
   machine: `SANDIA_DATA_DIR` (its SQLite DB, session secret, and TLS
   cert/key - a new machine should generate its own, not reuse another
   machine's), `SANDIA_BACKUP_DIR`, and of course that machine's own
   `dhcpd.conf`/`dhcpd.leases`. If you do want to carry users/audit history
   over, copy `<SANDIA_DATA_DIR>/sandia.db` explicitly; don't copy the
   TLS cert/key (regenerate them; a cert also embeds the old hostname/IP).
