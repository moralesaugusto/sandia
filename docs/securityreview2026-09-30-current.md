# Sandia Security Review — 2026-09-30 current snapshot

**Reviewed by:** OpenAI GPT-5 (Codex)

## Scope and method

This is a static security assessment of the repository at tag `v1.4.5`, inspected on 2026-09-30. It covers authentication, authorization, session handling, CSRF protection, browser responses, privileged DHCP configuration and service operations, outbound integrations, data storage, templates, dependencies, and operational defaults.

The assessment reviewed the current Python source, templates, tests, lockfile metadata, and prior security reviews. It did not include a deployed-environment penetration test, host/service-account or reverse-proxy review, dependency vulnerability database scan, network-egress test, or production-secret review. `pytest` was unavailable in the environment; `uv run pytest -q` could not start because `uv` could not create a temporary cache file. No test-suite result is claimed.

## Executive summary

The current tree has meaningful security controls: Argon2 password hashing, centralized role checks, global CSRF validation, session-cookie flags, loopback-by-default plain HTTP, separated subprocess arguments, atomic configuration replacement, and audit logging. The earlier fixed real-install administrator password finding is materially improved: real installs generate a random password, while the fixed `admin/admin` credential is retained for dummy mode.

The application is not ready to expose directly to an untrusted network. The highest-risk boundary is the administrator-configured Ollama integration: the server connects to arbitrary HTTP/HTTPS destinations and sends DHCP configuration, lease metadata, and logs to them. Privileged configuration replacement still uses shared predictable files without serialization or symlink/ownership hardening. Missing browser security headers, incomplete bootstrap-password lifecycle, weak login throttling, and unbounded AI request resources are additional concerns.

## Findings by risk

### High

#### SEC-C1 — Administrator-controlled Ollama URL enables SSRF and data export

**Impact:** The server can be induced by an administrator or compromised administrator account to connect to internal services, link-local/cloud metadata endpoints, or attacker-controlled hosts. Chat requests export DHCP configuration, active lease information, service status, and DHCP log data to the selected endpoint.

**Evidence:** `src/sandia/ai.py:52-67` validates only the URL scheme, hostname, and port. `src/sandia/ai.py:70-74,125-150` performs server-side HTTP requests without an address policy, redirect restriction, or destination revalidation. The context is assembled from configuration, leases, and logs in `src/sandia/ai.py:83-110`. The model-list endpoint triggers outbound access from `src/sandia/routers/ai.py:66-85`.

**Recommendation:** Prefer loopback or a configured Ollama allowlist. Resolve and validate all addresses immediately before connecting; reject link-local, multicast, loopback, private, and cloud-metadata ranges unless explicitly allowed by policy. Protect against DNS rebinding, set `follow_redirects=False`, bound response/body sizes, and disclose the data-export boundary to administrators.

#### SEC-C2 — Privileged configuration apply lacks serialization and filesystem hardening

**Impact:** Concurrent apply or restore requests can overwrite one another, validate one staged configuration and install another, or leave an unexpected configuration installed. If an untrusted local account can write in the configured DHCP directory, predictable staging and temporary names increase symlink/file-race risk while the application may run with elevated privileges.

**Evidence:** `src/sandia/dhcpd/apply.py:47-49` writes the shared `.sandia-staged.conf`; `:72-79` uses the fixed `*.sandia-tmp` sibling; and `:133-150` has no lock around stage, validation, installation, restart, and rollback. The application also invokes `systemctl` and may be run with root access through the documented deployment path.

**Recommendation:** Serialize apply, restore, and lease-file mutation operations with an application or filesystem lock. Use securely created per-operation temporary files with exclusive creation, reject symlinks, verify ownership and modes, and bind validation to the exact file installed. Prefer a least-privilege service account plus narrowly scoped privileged helper/policy for DHCP and service operations.

### Medium

#### SEC-C3 — No explicit browser security headers or Content Security Policy

**Impact:** Authenticated browser sessions have less defense in depth against clickjacking, MIME confusion, unsafe content execution, and future template/dependency mistakes. The application loads Tailwind, fonts, and HTMX from third-party CDNs without visible integrity pinning.

**Evidence:** `src/sandia/templates/base.html:7-38` loads external assets and inline scripts. No middleware or response-header implementation for CSP, frame protection, MIME sniffing, referrer policy, or permissions policy was identified.

**Recommendation:** Add deliberate headers including CSP with `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, restrictive `Referrer-Policy`, and an appropriate `Permissions-Policy`. Self-host assets or pin them with SRI. Replace inline scripts with nonces, hashes, or external files as CSP is tightened. Add response-header tests.

#### SEC-C4 — Initial administrator password remains a plaintext secret with no enforced rotation

**Impact:** During bootstrap, anyone who can read service logs or the data directory can authenticate as administrator. The generated password remains valid until the user changes it and manually deletes the artifact.

**Evidence:** `src/sandia/main.py:68-80` writes the password to `initial-admin-password` with mode `0600`, prints it to stdout, and only instructs the operator to change and delete it. No forced first-login password change or automatic invalidation is present.

**Recommendation:** Mark the account as requiring password change, force rotation on first login, invalidate/delete the bootstrap secret after successful rotation, and avoid printing the secret into long-lived logs. Verify data-directory ownership and mode, and treat backups/logs as credential-bearing during bootstrap.

#### SEC-C5 — Login throttling is process-local, username-only, and can cause account lockout

**Impact:** Restarting the process or using multiple workers bypasses throttling. Five failed attempts for a known username block that account for five minutes, allowing an attacker to deny access. The dictionary has no explicit global bound.

**Evidence:** `src/sandia/rate_limit.py:1-23` stores failures only in an in-memory map keyed by username. `src/sandia/routers/auth.py:34-45` applies the lock before authentication and does not include source-IP controls.

**Recommendation:** Add bounded per-IP and per-account controls, preferably through a shared store or reverse proxy. Use progressive backoff rather than a simple account-wide lockout, cap memory, and alert on repeated failures while retaining generic authentication errors.

#### SEC-C6 — AI request and output resource limits are incomplete

**Impact:** An authenticated user can submit an arbitrarily large JSON message list/content before server-side history truncation, and can hold an outbound streaming request for up to five minutes. This can consume application connections, memory, and Ollama capacity.

**Evidence:** `src/sandia/routers/ai.py:23-28` defines `messages` as an unconstrained list. `src/sandia/ai.py:114-122` limits message count but not content or total bytes; `:129-139` uses a 300-second read timeout and has no visible per-user concurrency or output-size limit.

**Recommendation:** Enforce message-count, per-message, total-byte, output-byte/token, timeout, concurrency, and per-user rate limits at validation and streaming boundaries. Cancel upstream work when the client disconnects and reject malformed/oversized streamed responses.

### Low / operational risk

#### SEC-C7 — Audit, backup, lease, and AI data need explicit retention and access controls

**Impact:** The database and backups can contain usernames, IP addresses, DHCP configuration, lease history, logs, and operational errors. Unbounded audit and backup growth can exhaust disk space, while broad local file access exposes network inventory.

**Evidence:** `src/sandia/audit.py:7-16` stores request IPs and arbitrary details; `src/sandia/routers/audit_router.py:12-20` exposes the newest 200 entries to operators; and `src/sandia/dhcpd/apply.py:82-100` creates timestamped backups without visible retention or rotation.

**Recommendation:** Define retention and rotation, redact unnecessary data and command output, bound audit-detail lengths, enforce database/backup ownership and modes, monitor disk space, and document that backups contain sensitive network information.

#### SEC-C8 — Dependency and runtime-asset supply-chain assurance is not demonstrated

**Impact:** The repository contains a lockfile, but this review did not run a vulnerability database scan. Browser assets are fetched from third-party CDNs at runtime, increasing dependence on external availability and integrity.

**Evidence:** Runtime dependencies are declared in `pyproject.toml` and resolved in `uv.lock`; `src/sandia/templates/base.html:8-11,38` references Google Fonts, Tailwind, and HTMX CDNs.

**Recommendation:** Add dependency vulnerability scanning and lockfile review to CI, update dependencies regularly, and self-host or integrity-pin browser assets. Include an asset availability/integrity decision in the deployment checklist.

## Positive controls observed

- Passwords are hashed with Argon2 in `src/sandia/security.py:10-24`.
- Role checks are centralized and applied to privileged routes through `require_role`.
- Unsafe requests require a per-session CSRF token, including form, HTMX, and JSON paths (`src/sandia/csrf.py:19-37` and the app-wide dependency in `src/sandia/main.py:89`).
- Session cookies are explicitly named, `HttpOnly` by middleware default, `SameSite=Lax`, and secure when HTTPS is enabled (`src/sandia/main.py:108-114`).
- Real installs generate a random initial administrator password, and session/bootstrap/TLS secrets use restrictive file modes (`src/sandia/main.py:68-80`, `src/sandia/tls.py:44-52`).
- Subprocesses use argument-separated execution rather than shell interpolation (`src/sandia/dhcpd/apply.py:32-44`).
- Configuration installation uses a sibling-file replacement and attempts rollback after service failure.
- Backup restore rejects path separators and requires a regular file (`src/sandia/routers/backups.py:37-42`).
- Jinja autoescaping is used, and AI responses are inserted with `textContent` in the browser rather than model output being treated as HTML.

## Prioritized to-do list

### Immediate — before network exposure

- [ ] Restrict Ollama destinations, block sensitive address ranges and redirect/rebinding paths, and document the data-export boundary.
- [ ] Add a lock and secure per-operation temporary files with symlink/ownership checks for configuration apply and restore.
- [ ] Add security headers/CSP and self-host or integrity-pin third-party assets.
- [ ] Require first-login password rotation and remove/invalidate the bootstrap password artifact after use.

### Next — before production use

- [ ] Enforce AI input/output size, timeout, concurrency, and per-user rate limits.
- [ ] Replace username-only in-memory login throttling with bounded per-IP/per-account controls.
- [ ] Define audit/database/backup permissions, redaction, retention, rotation, and disk monitoring.
- [ ] Add regression tests for SSRF policy, redirects, DNS rebinding, headers/CSP, concurrent apply, symlink defenses, bootstrap rotation, and AI limits.

### Ongoing assurance

- [ ] Run the complete pytest suite in an environment with the development dependencies available and investigate any hangs or failures.
- [ ] Add dependency vulnerability scanning and runtime asset integrity checks to CI.
- [ ] Document reverse-proxy/TLS settings, firewall exposure, service-account permissions, privileged helper policy, backup handling, and log access.
- [ ] Perform an authenticated penetration test against a representative deployment.

## Overall risk rating

**High before remediation.** CSRF and fixed real-install credentials are materially improved in the current tree, but unrestricted administrator-controlled outbound requests and privileged, weakly serialized file/service operations can still create significant confidentiality, integrity, and availability impact. Until those boundaries are restricted and tested, deploy only behind a trusted network boundary with least-privilege host permissions and controlled egress.
