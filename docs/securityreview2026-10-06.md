# Sandia Security Review — 2026-10-06

**Reviewed by:** OpenAI GPT-5 (Codex)

## Scope and method

This is a static security assessment of the repository at version `1.4.6`, inspected on 2026-10-06. It covers authentication and authorization, session and CSRF handling, the new configuration review and rollback workflow, privileged DHCP configuration and service operations, outbound integrations, file storage, templates, dependencies, and operational defaults. The previous security reviews in `docs/` were used as reference.

The review did not include a deployed-environment penetration test, reverse-proxy or host/service-account review, dependency vulnerability database scan, network-egress test, or production-secret review. `pytest` was not installed. `uv run pytest -q` could not start because `uv` could not create its temporary cache file on the read-only filesystem. No test-suite pass/fail result is claimed.

## Executive summary

The current tree has meaningful security controls: Argon2 password hashing, centralized RBAC, global CSRF validation, hardened session-cookie settings, random real-install bootstrap credentials, argument-separated subprocesses, configuration validation before installation, stale-change detection, per-user expiring review tokens, and an explicit post-apply rollback window.

The application is still not ready to expose directly to an untrusted network. The highest-risk boundary remains the administrator-configured Ollama integration: the server connects to arbitrary HTTP/HTTPS destinations and sends DHCP configuration, lease metadata, and logs to them. Privileged configuration replacement and rollback remain shared-file operations without serialization or symlink/ownership hardening. Missing browser security headers, the plaintext bootstrap-password lifecycle, weak login throttling, and incomplete AI request/resource limits remain important residual concerns.

## Findings by risk

### High

#### SEC-2026-01 — Administrator-controlled Ollama URL enables SSRF and data export

**Impact:** The server can be made to connect to internal services, link-local/cloud metadata endpoints, or attacker-controlled hosts selected through the admin AI settings. Chat requests export DHCP configuration, active lease information, service status, and recent DHCP log data to the selected endpoint. The model-list GET endpoint also causes a server-side request.

**Evidence:** `src/sandia/ai.py:66-81` validates only the URL scheme, hostname, and port. `src/sandia/ai.py:84-88,146-171` performs requests without an address policy, redirect restriction, destination revalidation, response-size limit, or DNS-rebinding protection. The context is assembled from configuration, leases, service status, and logs in `src/sandia/ai.py:101-132`. The admin model-list route invokes the outbound request in `src/sandia/routers/ai.py:86-105`.

**Recommendation:** Prefer loopback or a configured Ollama allowlist. Resolve and validate all addresses immediately before connecting; reject loopback, private, link-local, multicast, and cloud-metadata ranges unless explicitly allowed by policy. Disable redirects or revalidate every redirect destination, protect against DNS rebinding, bound response/body sizes, and disclose the data-export boundary to administrators. Consider separating model discovery from arbitrary user-supplied URLs.

#### SEC-2026-02 — Privileged apply and rollback operations lack serialization and filesystem hardening

**Impact:** Concurrent apply, restore, or rollback requests can overwrite each other, validate one staged configuration and install another, or record an incorrect rollback target. The shared staging and temporary names also create symlink/file-race risk if an untrusted local account can write in the configured DHCP directory while Sandia has elevated privileges.

**Evidence:** `src/sandia/dhcpd/apply.py:49-52` writes the shared `.sandia-staged.conf`; `:74-81` copies through the fixed `*.sandia-tmp` sibling; and `:135-171` has no lock around stage, validation, installation, service reload/restart, and rollback. Merely opening a review page stages the proposal (`src/sandia/routers/review.py:44-50`). Rollback reads a shared backup and invokes the same unlocked pipeline (`src/sandia/routers/review.py:111-129`). The documented deployment path can run the application with root access.

**Recommendation:** Serialize apply, restore, and rollback with an application or filesystem lock covering the complete operation. Use securely created per-operation temporary files with exclusive creation, reject symlinks, verify ownership and modes, and bind validation to the exact file installed. Avoid mutating a shared staging path during a GET review. Prefer a least-privilege service account plus a narrowly scoped privileged helper/policy for DHCP and service operations.

### Medium

#### SEC-2026-03 — Pending changes and rollback metadata are plaintext files without explicit restrictive modes

**Impact:** Proposed and previously installed DHCP configurations can contain network inventory, comments, hostnames, and possibly operational secrets. The pending-change and last-apply files are written using ordinary `write_text()` calls, so their effective permissions depend on the process umask. Anyone who can read the data directory may inspect proposals and rollback metadata; anyone who can modify them may affect the review or rollback workflow.

**Evidence:** `src/sandia/pending_changes.py:55-78` stores full proposed configuration text and user/action metadata as JSON under `data_dir/pending`; `src/sandia/rollback_window.py:31-38` stores the backup name and installed hash in `last-apply.json`. Neither path explicitly creates files with `0600` mode or verifies parent ownership/mode. Backup contents are also read directly by `src/sandia/routers/review.py:124`.

**Recommendation:** Create the data directory and all security-sensitive state files with restrictive modes, use exclusive creation plus atomic replacement, verify ownership and reject symlinks, and document the required parent-directory permissions. Treat pending files, rollback records, backups, the SQLite database, logs, and the bootstrap artifact as sensitive. Add tests for modes, symlink replacement, malformed state, and concurrent writers.

#### SEC-2026-04 — No explicit browser security headers or Content Security Policy

**Impact:** Authenticated browser sessions have less defense in depth against clickjacking, MIME confusion, unsafe content execution, and future template/dependency mistakes. The application loads Tailwind, fonts, and HTMX from third-party CDNs without visible integrity pinning and uses inline scripts.

**Evidence:** `src/sandia/templates/base.html:7-38` loads external assets and inline JavaScript. No middleware or response-header implementation for CSP, frame protection, MIME sniffing, referrer policy, or permissions policy was identified.

**Recommendation:** Add deliberate headers including CSP with `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, a restrictive `Referrer-Policy`, and an appropriate `Permissions-Policy`. Self-host assets or pin them with SRI. Replace inline scripts with nonces, hashes, or external files as CSP is tightened. Add response-header regression tests.

#### SEC-2026-05 — Initial administrator password remains a plaintext secret with no enforced rotation

**Impact:** During bootstrap, anyone who can read service logs or the data directory can authenticate as administrator. The generated password remains valid until the user changes it manually and deletes the artifact.

**Evidence:** `src/sandia/main.py:68-80` writes the password to `initial-admin-password` with mode `0600`, prints it to stdout, and only instructs the operator to change and delete it. There is no forced first-login password change or automatic invalidation after rotation. Dummy mode intentionally retains `admin/admin` (`src/sandia/main.py:64-67`).

**Recommendation:** Mark the account as requiring a password change, force rotation on first login, invalidate/delete the bootstrap secret after successful rotation, and avoid printing the secret into long-lived logs. Verify data-directory ownership and mode. Keep dummy mode loopback-only or require an explicit unsafe-exposure override.

#### SEC-2026-06 — Login throttling is process-local, username-only, and can cause account lockout

**Impact:** Restarting the process or using multiple workers bypasses throttling. Five failed attempts for a known username block that account for five minutes, allowing an attacker to deny access. The in-memory map has no explicit global bound.

**Evidence:** `src/sandia/rate_limit.py:1-38` stores failures only in an in-memory dictionary keyed by normalized username. `src/sandia/routers/auth.py:34-45` checks the account key before authentication and does not include source-IP controls.

**Recommendation:** Add bounded per-IP and per-account controls, preferably through a shared store or reverse proxy. Use progressive backoff rather than a simple account-wide lockout, cap memory growth, and alert on repeated failures while retaining generic authentication errors.

#### SEC-2026-07 — AI request and streaming resource limits remain incomplete

**Impact:** The browser can submit an arbitrarily large JSON `messages` list before server-side history truncation. The server then holds an outbound streaming request for up to five minutes, with no visible per-user concurrency limit or hard output-byte limit. This can consume application connections, memory, and Ollama capacity.

**Evidence:** `src/sandia/routers/ai.py:33-36` declares `messages` as an unconstrained list. `src/sandia/ai.py:135-143` bounds retained message count and content length only after request parsing, while `:152-169` uses a 300-second read timeout and streams without a response-size or concurrency bound.

**Recommendation:** Enforce request-body, message-count, per-message, and total-byte limits at validation time. Bound output bytes/tokens and total duration, add per-user concurrency/rate limits, cancel upstream work when the client disconnects, and reject malformed or oversized streamed responses.

### Low / operational risk

#### SEC-2026-08 — Audit, backup, lease, and AI data need explicit retention and access controls

**Impact:** The database and backups can contain usernames, source IPs, DHCP configuration, lease history, logs, proposed changes, and operational errors. Unbounded audit and backup growth can exhaust disk space, while broad local file access exposes network inventory.

**Evidence:** `src/sandia/audit.py:7-16` stores request IPs and arbitrary details; `src/sandia/routers/audit_router.py:12-20` exposes the newest 200 entries to operators; and `src/sandia/dhcpd/apply.py:91-99` creates timestamped backups without visible retention or rotation.

**Recommendation:** Define retention and rotation, redact unnecessary data, bound audit-detail lengths, enforce database/backup ownership and modes, monitor disk space, and document that backups and AI context contain sensitive network information.

#### SEC-2026-09 — Dependency and runtime-asset supply-chain assurance is not demonstrated

**Impact:** The repository contains a lockfile, but this review did not run a vulnerability database scan. Browser assets are fetched from third-party CDNs at runtime, increasing dependence on external availability and integrity. The optional OUI refresh also downloads and parses a remote file in a background thread without a visible response-size bound (`src/sandia/oui_cache.py:106-122`).

**Recommendation:** Add dependency vulnerability scanning and lockfile review to CI, update dependencies regularly, and self-host or integrity-pin browser assets. Bound OUI download size before reading it into memory and retain the last known-good cache.

## Positive controls observed

- Passwords are hashed with Argon2 in `src/sandia/security.py:10-24`.
- Role checks are centralized and privileged routes use `require_role`.
- Unsafe requests require a matching per-session CSRF token through the app-wide dependency (`src/sandia/csrf.py:19-37`, `src/sandia/main.py:89`); the token rotates after login (`src/sandia/routers/auth.py:47-50`).
- Session cookies have an explicit name, `SameSite=Lax`, and `Secure` when HTTPS is enabled (`src/sandia/main.py:108-114`).
- Real installs generate a random initial administrator password, and session/bootstrap/TLS secrets use restrictive file modes (`src/sandia/main.py:68-80`, `src/sandia/tls.py:44-52`).
- Review tokens are cryptographically random, expire after one hour, are single-use on apply/cancel, and are bound to their creating username (`src/sandia/pending_changes.py:37-92`, `src/sandia/routers/review.py:79-107`).
- Apply refuses a stale live configuration by comparing the captured base hash (`src/sandia/routers/review.py:81-83`). Rollback is available only for ten minutes while the installed hash remains current (`src/sandia/rollback_window.py:15-57`).
- Subprocesses use argument-separated execution, not shell interpolation (`src/sandia/dhcpd/apply.py:38-46`).
- Backup restoration is routed through the review workflow and local redirect targets are constrained (`src/sandia/routers/backups.py:22-35`, `src/sandia/routers/review.py:33-35`).
- Jinja autoescaping is used, and AI responses are inserted with `textContent` rather than model output being treated as HTML (`src/sandia/templates/base.html:342-346,425-432`).

## Prioritized to-do list

### Immediate — before network exposure

- [ ] Restrict Ollama destinations, block sensitive address ranges and redirect/rebinding paths, and document the data-export boundary.
- [ ] Add a lock and secure per-operation temporary files with symlink/ownership checks for configuration apply, restore, and rollback.
- [ ] Add security headers/CSP and self-host or integrity-pin third-party assets.
- [ ] Require first-login password rotation and remove/invalidate the bootstrap password artifact after use.

### Next — before production use

- [ ] Enforce AI request-size, output-size, timeout, concurrency, and per-user rate limits.
- [ ] Replace username-only in-memory login throttling with bounded per-IP/per-account controls.
- [ ] Secure pending-change, rollback, database, backup, and cache file permissions and retention.
- [ ] Add regression tests for SSRF policy, redirects, DNS rebinding, headers/CSP, concurrent apply, symlink defenses, state-file modes, bootstrap rotation, and AI limits.

### Ongoing assurance

- [ ] Run the complete pytest suite in an environment with development dependencies and a writable `uv` cache.
- [ ] Add dependency vulnerability scanning and runtime asset integrity checks to CI.
- [ ] Document reverse-proxy/TLS settings, firewall exposure, service-account permissions, privileged helper policy, backup handling, and log access.
- [ ] Perform an authenticated penetration test against a representative deployment.

## Overall risk rating

**High before remediation.** CSRF, session-cookie configuration, and fixed real-install credentials are materially improved. However, unrestricted administrator-controlled outbound requests and privileged, weakly serialized filesystem/service operations can still create significant confidentiality, integrity, and availability impact. Until those boundaries are restricted and tested, deploy only behind a trusted network boundary with least-privilege host permissions and controlled egress.
