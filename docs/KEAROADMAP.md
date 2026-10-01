# Kea Roadmap

Kea DHCPv4 has full feature parity with the legacy ISC backend as of 1.4.5,
and is the default and only supported backend. Behavior is described in
`INSTRUCTIONS.md` ("Kea DHCPv4") and the design in `DECISIONS.md`.

## Done in 1.4.5

- Subnet, reservation and global-settings editors write `kea-dhcp4.conf`,
  changing only what was edited (comments and unmodeled keys kept).
- Interfaces editor for `Dhcp4.interfaces-config.interfaces`, through the
  validate/apply pipeline.
- Deny client via a Sandia-managed `DROP` class (`pkt4.mac == 0x...`); a
  hand-written DROP class is left alone.
- Lease deletion with `lease4-del` over the control socket. Lease file
  compaction is left to Kea's LFC.
- `<?include?>` followed by the read views (relative to `/`, ten levels).
- Every pool of a subnet shown on the map and counted in utilization and
  diagnostics (also for ISC subnets with several ranges).
- Systemd journal as the default Kea log source.
- Client diagnostics explain that DISCOVER/REQUEST/NAK need debug logging.
- Backend-neutral wording in diagnostics and the AI prompt.
- `config-reload` over the control socket instead of a restart.
- Kea 2.7.9+/3.x path restrictions and the upstream unit name documented.

## Known limits (not parity gaps)

- The editors don't patch configs that use `<?include?>`; edit those on Raw
  Config. Patching the right included file is possible future work.
- Reservations identified by `client-id`, `circuit-id` or `flex-id` are shown
  by IP with no MAC, so they aren't linked to devices. The ISC backend
  doesn't link its `dhcp-client-identifier` hosts either.

## Out of scope until there's a concrete need

- SQL lease and host backends (MySQL/PostgreSQL); host reservations stored
  in a database are not shown.
- DHCPv6 (`kea-dhcp6`).
- High availability pairs and the Control Agent REST API.
