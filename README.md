# Sandia

*Sandía* is Spanish for watermelon - the theme (logo, color palette) runs
with it. Under the fruit, it's a standalone web UI for managing an ISC
isc-dhcp-server instance: edit
dhcpd.conf (scopes, options, static reservations), visualize a subnet's pool
as an SVG address grid, browse and search leases (with MAC vendor lookup,
CSV export, and a right-click reserve/deny menu), restart and check the
service, diff/back up/restore config, and manage users with role-based
access (admin / operator / viewer) and login rate-limiting. No service account or systemd unit - run it as yourself, or
with `sudo` when it needs to touch real system files. Binds to `0.0.0.0`
on port `7001` and serves over HTTPS by default (self-signed
elliptic-curve certificate, generated automatically), with HTTPS optional
via `SANDIA_HTTPS=0`.

See `INSTRUCTIONS.md` for setup, configuration and usage (including running
with dummy data, running for real with `sudo`, and porting to another
machine), and `CHANGELOG.md` for release history.

```
uv run sandia            # or: uv run sandia --dummy  (try it with no setup)
uv run pytest
```
