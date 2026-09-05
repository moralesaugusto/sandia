# Instructions

## What this is

Sandia is a web UI for managing an ISC `isc-dhcp-server` instance:

- Edit `dhcpd.conf` - global settings, subnets/scopes, static reservations,
  or the raw file directly (with a diff preview before applying).
- Browse and search leases, with MAC vendor identification, CSV export,
  and a right-click menu to reserve or deny a client from an observed
  lease.
- Restart/enable/disable/check the `isc-dhcp-server` service.
- Back up and restore config, with a diff shown before any apply.
- Manage users with role-based access (admin / operator / viewer),
  audit logging, and login rate-limiting.

All config changes go through the same path: stage the new config,
validate it (`dhcpd -t`), back up the live file, then install it - so a
bad edit never reaches the running server.

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

This starts the server bound to `0.0.0.0` (reachable from other machines on
the network, not just localhost). On first startup it also:

- Creates `sandia.db` (SQLite) and either prints a **generated admin
  password** to stdout (copy it before it scrolls away) or, in dummy mode,
  creates the fixed testing-only login `admin` / `admin` instead (see
  "Changing a password" below to change either one).
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
  `/etc/dhcp/dhcpd.conf` with a timestamp, then copies the staged file over
  it. Validation only needs to read the staging file (usually fine without
  root); the backup+install step needs write access to `/etc/dhcp/` and
  `SANDIA_BACKUP_DIR`, so it needs `sudo` in a normal install.
- **Restart/enable/disable/status**: calls `systemctl <action> isc-dhcp-server`
  directly. Restart/enable/disable need `sudo`; status usually doesn't.
- If a command isn't available or isn't permitted, the app reports the
  failure in the UI (a flash message and an audit log entry) instead of
  crashing - the live config is left untouched.

In short: run the app as yourself day-to-day (browsing leases, dummy mode,
editing config drafts), and re-run it with `sudo` for the session where you
actually want to apply that config or restart the service.

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

`admin` / `admin` (dummy mode) is a fixed, publicly-known testing password -
change it (and any other account's password) any of these ways:

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
   (fixed `admin`/`admin` in dummy mode, a fresh random password otherwise).
   Only do this when you don't need anything in the existing database.

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
```

65+ tests cover the `dhcpd.conf` parser/serializer (round-trip and
idempotence), the leases file parser, the stage/validate/apply pipeline,
TLS certificate generation, dummy mode, the CLI flags (including
`--set-password`), MAC vendor lookup, the config diff, login
rate-limiting, and the full HTTP route layer (login, RBAC boundaries,
subnet/reservation CRUD, self-service password change, the "reserve from
lease" flow, and config-validation failure paths).

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
