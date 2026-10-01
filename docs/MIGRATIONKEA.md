# DHCP Backend Migration Plan: ISC DHCP / Kea

## Objective

Add support for **Kea DHCP** to Sandia while preserving the existing **ISC DHCP** behavior exactly as it works today.

The migration must be deliberately conservative:

- **Do not add, remove, rename, reinterpret, or silently change any existing setting.**
- **Touch the minimum number of files and lines possible.**
- Keep the current ISC DHCP path as the default for backward compatibility.
- Add **one explicit backend setting** that selects the DHCP implementation.
- Keep the code clean by isolating backend-specific behavior behind a small interface rather than spreading `if kea` / `if isc` checks throughout the application.
- Preserve current UI behavior, RBAC, audit logging, rollback behavior, dummy mode, and existing parser semantics unless a backend-specific difference genuinely requires an adapter.
- Do not perform a broad refactor. This is a compatibility extension, not a rewrite.

Repository inspected: `moralesaugusto/sandia`, branch `main`.

Current architecture already has useful seams around `Settings`, `dhcpd/apply.py`, lease/log loading, diagnostics, and `INTERFACESv4`. The current integration is explicitly ISC-oriented, including:
- `DHCPD_CONF_PATH` defaulting to `/etc/dhcp/dhcpd.conf`
- `DHCPD_LEASES_PATH` defaulting to `/var/lib/dhcp/dhcpd.leases`
- `SANDIA_INTERFACES_CONF` defaulting to `/etc/default/isc-dhcp-server`
- `SANDIA_SERVICE_NAME` defaulting to `isc-dhcp-server`
- configuration validation through `dhcpd -t -cf ...`
- service control through `systemctl <action> <service>`
- diagnostics/log parsing based on ISC `dhcpd` syslog output

The existing test suite is extensive, including apply/rollback, parser round-trip, leases, diagnostics, interfaces, routes, dummy mode, and configuration tests. Use these tests as compatibility guardrails.

---

## 1. First: establish the exact current contract

Before changing code, Claude should inspect and document the current behavior of:

1. `src/sandia/config.py`
2. `src/sandia/dhcpd/apply.py`
3. `src/sandia/leases.py`
4. `src/sandia/leases_cleanup.py`
5. `src/sandia/diagnostics/dhcp_log.py`
6. `src/sandia/diagnostics/server.py`
7. `src/sandia/interfaces_conf.py`
8. `src/sandia/routers/global_settings.py`
9. `src/sandia/routers/service.py`
10. existing settings/service/diagnostics/lease tests
11. `README.md`, `INSTRUCTIONS.md`, `CLAUDE.md`, and relevant decision/current-state docs

Do not assume that every current ISC-specific behavior should be reproduced for Kea. Identify which behaviors are **backend-neutral** and which are **ISC-specific**.

### Important compatibility rule

The existing defaults must remain exactly unchanged when the new backend setting is absent.

That means a current installation must continue to behave as an ISC DHCP installation without requiring any configuration migration.

---

## 2. Verify Kea's current operational interface before implementation

Use authoritative current Kea documentation and package/system behavior to determine, for the supported Kea release(s):

- configuration file format and whether Sandia can safely preserve unknown directives
- configuration validation command/API
- service unit naming conventions
- restart/reload/status/enable/disable behavior
- lease database format(s)
- supported lease backends
- log format(s)
- interface/listening configuration
- how configuration is applied safely
- whether Kea supports a control socket / REST interface relevant to future management
- whether a minimal deployment can use files + systemd without introducing a new service dependency

Do **not** invent an abstraction based on assumptions about Kea.

The plan should choose the smallest integration surface that is actually supported.

---

## 3. Add exactly one new backend selector setting

Introduce one new setting, preferably named:

`SANDIA_DHCP_BACKEND`

Supported values:

- `isc`
- `kea`

Default:

- `isc`

Requirements:

- Existing deployments behave exactly as before.
- Invalid values fail clearly and early.
- Do not rename any existing environment variables.
- Do not replace existing ISC settings.
- Do not make existing ISC settings conditional in a way that changes their defaults.
- Document the new setting alongside the existing configuration table.

### Important design constraint

Do not create a large new configuration schema for Kea unless the current code absolutely requires it.

For the first migration, the selector should choose the backend implementation while the existing path-related settings remain backward compatible.

Where Kea needs different paths, determine whether those should be:
- derived from existing settings without changing their meaning, or
- exposed through a **very small number of additional backend-specific settings only if technically unavoidable**.

Do not add speculative settings.

---

## 4. Introduce a minimal backend boundary

Create a small internal abstraction, preferably under:

`src/sandia/dhcpd/`

For example, conceptually:

- `backend.py`
- or a similarly small module if an existing file is a better seam

The abstraction should cover only the operations Sandia actually needs:

### Configuration operations
- validate configuration
- validate live configuration
- install/apply configuration

### Service operations
- restart
- enable
- disable
- status
- enabled state

### Runtime data
- load leases
- load DHCP events/logs

Do not force unrelated parser/model code through the abstraction.

### Avoid this anti-pattern

Do not scatter code like:

```python
if settings.dhcp_backend == "kea":
    ...
else:
    ...
```

through routers, diagnostics, lease pages, and helpers.

Prefer selecting a backend once and calling a small common interface.

---

## 5. Preserve the current ISC implementation nearly verbatim

The ISC backend should retain the current behavior of `src/sandia/dhcpd/apply.py` with as little movement as possible.

In particular, preserve:

- `dhcpd -t -cf <staging>`
- atomic replacement of the live configuration
- timestamped backup before installation
- file mode preservation
- restart + status verification
- rollback when restart/status fails
- clean handling when `dhcpd` is missing
- dummy-mode service simulation
- current `SANDIA_SERVICE_NAME` behavior

Refactor only enough to place these operations behind the backend boundary.

### Compatibility test requirement

All existing ISC apply workflow tests must continue to pass unchanged wherever practical.

Do not rewrite tests simply because the implementation moved.

---

## 6. Kea configuration handling

Kea configuration is structurally different from ISC `dhcpd.conf`.

Do **not** force Kea JSON through the existing ISC AST/parser/serializer.

For Kea:

- Treat the Kea configuration as its own format.
- Preserve unknown Kea settings where Sandia is not explicitly modeling them.
- Avoid broad conversion of existing ISC configuration objects into Kea.
- Do not pretend an ISC `subnet`/reservation/global-option model maps 1:1 to Kea when it does not.

### First migration scope

The plan should determine whether the existing UI can safely operate in Kea mode with:

1. raw Kea configuration editing/validation/application, while
2. existing ISC-specific structured editors remain restricted or clearly identified as ISC-only.

Do not silently generate incomplete Kea configuration from an ISC data model.

This is a critical correctness requirement.

---

## 7. Existing global settings page

Current `/settings` edits ISC-style global DHCP directives such as:

- authoritative
- default lease time
- max lease time
- domain name
- DNS servers
- NTP servers

Do not reinterpret these fields for Kea unless there is a demonstrably safe mapping.

Plan for one of these conservative behaviors:

- keep the existing structured settings active only for ISC and provide a clear backend-specific path for Kea, or
- expose only fields that have a correct Kea representation and preserve everything else as raw config.

Do not change the meaning of existing fields for ISC.

---

## 8. Reservations/subnets/parser scope

The existing ISC parser/serializer is a major part of the application.

Do **not** rewrite it into a generic DHCP parser.

For this migration:

- Keep ISC AST/parser/serializer intact.
- Add Kea-specific parsing only where needed.
- Avoid a premature universal DHCP AST.
- Preserve unknown content rather than deleting it.

The plan should explicitly identify which existing pages depend on ISC AST types:

- subnets
- reservations
- global settings
- subnet map
- config diff
- raw config

Then classify them:

| Feature | ISC backend | Kea backend |
|---|---|---|
| Raw config view/edit | Preserve | Support Kea format |
| Config validation | `dhcpd -t` | Kea-native validation |
| Structured subnet editor | Existing behavior | Do not fake mapping |
| Reservation editor | Existing behavior | Do not fake mapping |
| Global settings | Existing behavior | Only safe mappings |
| Diff | Existing behavior | Text/format-aware as appropriate |

---

## 9. Lease support

The current `leases.py` parses ISC `dhcpd.leases`.

Do not attempt to make that parser understand Kea database files by adding increasingly complicated regexes.

Instead:

- retain the ISC lease loader unchanged
- add a Kea lease adapter for the actual supported Kea lease backend
- normalize both into the existing application-level `Lease` model only where the required fields genuinely exist
- preserve missing/unknown values honestly

Investigate Kea's supported lease storage before deciding implementation details.

### Lease cleanup

The current lease cleanup logic directly edits the ISC leases text file.

This must **not** run against a Kea lease database unless Kea explicitly supports that operation safely.

For Kea mode:

- disable/hide the ISC-only cleanup action, or
- replace it with a Kea-native operation only if there is a safe documented mechanism.

Do not corrupt or rewrite a live Kea database.

---

## 10. Interface configuration

The current `interfaces_conf.py` logic manages:

`INTERFACESv4` in `/etc/default/isc-dhcp-server`

This is specifically an ISC service configuration mechanism.

Do not reuse this file or setting for Kea by pretending it has the same semantics.

Plan:

- ISC: preserve current Interfaces page exactly.
- Kea: determine Kea's actual interface configuration mechanism.
- Only add a Kea interface editor if it can be implemented without disturbing the ISC path.
- Avoid creating a fake `INTERFACESv4` equivalent.

The current subnet interface tags are organizational metadata and should remain so unless a correct Kea live directive exists.

---

## 11. Service integration

The current service integration assumes systemd and `SANDIA_SERVICE_NAME`.

Preserve that.

For Kea:

- determine the exact service unit(s) used by the chosen Kea package/deployment
- use the existing service abstraction
- default Kea service name only when the new backend is selected
- preserve explicit `SANDIA_SERVICE_NAME` override behavior

Do not remove or rename `SANDIA_SERVICE_NAME`.

Be careful if a Kea deployment requires multiple daemon services, for example DHCPv4 vs DHCPv6. Do not invent multi-service support in this migration unless the current application genuinely needs it. Document the chosen scope.

---

## 12. Diagnostics

Current diagnostics contain ISC-specific assumptions:

- service name text references `isc-dhcp-server`
- configuration check invokes `dhcpd -t`
- log parser expects `dhcpd` syslog lines
- interfaces check expects `INTERFACESv4`

Split diagnostics only at the backend-specific edge.

Keep the diagnostic result model, confidence model, findings, evidence, and overall decision logic unchanged.

Backend-specific checks should provide the same normalized result shape.

### Important

Do not make diagnostics claim:

> "configuration is invalid"

when the backend's validation binary/API is missing or unavailable.

Preserve the current distinction between:
- validator could not run
- validator ran and rejected config

Add corresponding tests for Kea.

---

## 13. Logging/events

The current event parser is explicitly ISC `dhcpd`-oriented.

For Kea:

- determine the actual default Kea log format for the selected deployment
- implement a Kea event parser/adapter if useful
- normalize only the event data needed by existing diagnostics/device/wall-of-shame code
- keep unsupported event fields as `None` rather than guessing

Do not rewrite the existing ISC regex parser.

The existing wall-of-shame calculations should remain based on normalized events/lease history. They should not know whether the source was ISC or Kea.

---

## 14. Dummy mode

Dummy mode must remain safe and self-contained.

Do not let enabling Kea cause dummy mode to touch:

- `/etc`
- real Kea files
- real ISC files
- real lease databases
- real systemd services

The backend selected in dummy mode should be simulated or sandboxed.

Preserve the current guarantee that dummy mode cannot overwrite real system configuration.

Add only the minimum dummy fixture/config needed for Kea tests.

---

## 15. UI requirements

Add the backend selector in the smallest logical place, likely the existing Global Settings or an administrative system configuration area.

The selector should:

- show current backend
- persist according to the existing settings mechanism
- default to ISC
- make it obvious which backend is active

Do not redesign the UI.

When Kea mode is active, avoid presenting controls that would execute ISC-specific operations unless those controls are genuinely backend-neutral.

Prefer a small backend badge/label and selective disabling/hiding over a large UI rewrite.

---

## 16. Persistence design

Determine where the new backend selector should live based on the existing architecture.

Priority order:

1. Reuse an existing settings persistence mechanism if one already exists.
2. Prefer a single environment variable if the application is intentionally environment-configured.
3. Do not add a database migration solely for this selector unless the architecture makes it clearly necessary.

The setting must not silently reset on every restart.

Document exactly how it is selected and what overrides what.

---

## 17. Testing plan

Add focused tests without rewriting the existing suite.

### Configuration
- default backend is `isc`
- `SANDIA_DHCP_BACKEND=isc`
- `SANDIA_DHCP_BACKEND=kea`
- invalid backend fails clearly
- existing settings retain their current defaults

### Backend selection
- selecting ISC returns the ISC implementation
- selecting Kea returns the Kea implementation
- no import-time side effects

### ISC regression
Run the existing test suite and ensure:
- parser tests unchanged/passing
- apply workflow unchanged/passing
- diagnostics unchanged/passing
- leases unchanged/passing
- interfaces tests unchanged/passing
- route tests unchanged/passing
- dummy mode unchanged/passing

### Kea validation
Test:
- valid Kea config
- invalid Kea config
- validator missing
- validator permission failure
- live-config validation vs staged-config validation

### Kea service
Test mocked:
- restart
- status
- enable
- disable
- command missing
- failed restart

### Kea rollback
Preserve the same safety contract:
- backup before apply
- install atomically
- restart
- verify active
- rollback on failure
- verify rollback

### Kea lease normalization
Test only the fields the application genuinely uses.

### Kea logs
Test representative real Kea log lines obtained from authoritative/current documentation or a real supported package deployment.

### Dummy mode
Ensure selecting Kea in dummy mode never touches real system paths or systemd.

---

## 18. Documentation updates

Update documentation only where necessary:

- `README.md`
- `INSTRUCTIONS.md`
- possibly `docs/CURRENT_STATE.md`
- `docs/DECISIONS.md`

Document:

- `SANDIA_DHCP_BACKEND`
- ISC remains the default
- supported Kea deployment assumptions
- which UI features are backend-specific
- lease storage assumptions
- service assumptions
- migration procedure
- rollback procedure
- limitations

Do not rewrite unrelated documentation.

---

## 19. Migration procedure

Claude's implementation plan should include a safe operator migration:

### Phase A: no-impact preparation
1. Leave backend at `isc`.
2. Install Kea separately.
3. Create/validate Kea configuration independently.
4. Confirm Kea service can start without touching ISC service state.

### Phase B: Sandia support
1. Deploy the code with backend support while still using `isc`.
2. Run the complete test suite.
3. Test Kea in dummy/sandbox mode.
4. Test Kea against a non-production Kea instance if available.

### Phase C: cutover
1. Back up existing ISC configuration and lease state.
2. Stop/disable ISC DHCP according to the deployment plan.
3. Enable/select Kea backend.
4. Start Kea.
5. Validate service status.
6. Validate clients obtain leases.
7. Verify Sandia reads the expected Kea leases/events.
8. Verify Sandia apply/rollback works.

### Phase D: rollback
The plan must explicitly describe returning to ISC without changing existing ISC settings.

Never require destructive conversion of the old ISC configuration.

---

## 20. Code cleanliness rules

Claude should follow these rules strictly:

- Prefer composition over conditionals.
- Keep backend-specific code together.
- Keep the existing ISC code recognizable.
- Do not introduce an elaborate plugin framework.
- Do not create generic abstractions before the second real use case requires them.
- No speculative support for DHCPv6 unless required by the existing app.
- No dependency additions unless there is a clear need.
- Prefer standard-library/process/system APIs already used in the project.
- Keep functions small and typed.
- Reuse existing `CommandResult`, `Settings`, audit, RBAC, and rendering models where appropriate.
- Do not duplicate rollback logic between ISC and Kea if a clean shared implementation can safely be extracted.
- Do not duplicate path/default resolution logic unnecessarily.
- Do not change unrelated formatting or files.

---

## 21. Definition of done

The migration plan is complete only when all of the following are true:

- `SANDIA_DHCP_BACKEND` selects ISC or Kea.
- ISC remains the default.
- Existing ISC deployments require no migration.
- Existing ISC settings preserve their exact current defaults and semantics.
- Kea configuration can be validated, applied, restarted, and verified safely.
- Apply failure can roll back safely.
- Leases/events are read through backend-specific adapters.
- ISC lease cleanup never touches a Kea lease database.
- ISC `INTERFACESv4` handling remains unchanged.
- Diagnostics do not make ISC-specific claims in Kea mode.
- Dummy mode remains isolated.
- Existing tests continue to pass.
- New Kea tests cover the backend boundary and safety behavior.
- Documentation accurately describes what is and is not supported.
- The final change set is small and reviewable.

---

## 22. Implementation order for Claude

Use this order and stop to reassess after each stage:

1. Inventory existing ISC coupling.
2. Verify current Kea commands, service behavior, config validation, lease storage, and logs from authoritative sources.
3. Add `SANDIA_DHCP_BACKEND=isc` setting with no behavior change.
4. Extract the smallest backend interface from current apply/service code.
5. Keep ISC implementation functionally identical.
6. Implement Kea backend behind that interface.
7. Add backend-specific lease/log adapters.
8. Adjust diagnostics to consume normalized backend operations.
9. Add the smallest necessary UI selector/state indicator.
10. Add targeted tests.
11. Run the entire existing suite.
12. Run lint/type checks already used by the project.
13. Review the diff specifically for accidental changes to existing settings/defaults.
14. Update only necessary documentation.

---

## 23. Final review checklist

Before considering the migration complete, Claude should inspect the final diff and answer:

- How many existing files changed?
- Which existing settings changed, if any?
- Were any defaults changed?
- Did any existing environment variable change meaning?
- Did any existing route change?
- Did any existing ISC parser behavior change?
- Can an existing ISC user run Sandia without setting the new variable?
- Can an existing ISC config be applied and rolled back exactly as before?
- Can Kea be selected without triggering ISC-only commands?
- Can a Kea failure roll back without corrupting configuration or leases?
- Are all backend-specific assumptions isolated?
- Did any unrelated refactoring sneak into the patch?

The goal is a **small compatibility layer**, not a DHCP architecture rewrite.