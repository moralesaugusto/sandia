# Sandia Security Review — 2026-09-30 re-run

## Executive summary

This review covers the current working tree after the recent security changes. The earlier findings for CSRF, session-cookie configuration, and the predictable real-install administrator password are substantially addressed:

- Unsafe requests now require a per-session CSRF token, supplied as a form field or `X-CSRF-Token` header.
- The session cookie is explicitly named, `HttpOnly`, `SameSite=Lax`, and `Secure` when HTTPS is enabled.
- Real installs generate a random initial admin password and save it in a `0600` file; only dummy mode retains `admin/admin`.
- Plain HTTP defaults to loopback binding.

The main residual risk is still the privileged deployment boundary. The AI integration permits server-side connections to arbitrary administrator-selected HTTP/HTTPS destinations and sends DHCP configuration, lease metadata, and logs to the selected destination. Browser security headers are still absent, and privileged configuration replacement remains vulnerable to concurrency/symlink-hardening concerns. These should be addressed before treating the application as safe for untrusted networks.

## Scope and limitations

Reviewed the current Python code, templates, tests, configuration, authentication/RBAC, CSRF middleware, TLS/session setup, AI integration, subprocess/file-write paths, audit logging, and relevant documentation.

This was a repository review, not a deployed penetration test. No dependency vulnerability database scan, host/service-account review, reverse-proxy review, or production-secret review was performed. The targeted pytest command (`tests/test_csrf.py`, `tests/test_routes.py`, `tests/test_ai.py`, and `tests/test_run_permission_errors.py`) stalled without producing a result and was interrupted; no test pass/fail conclusion is claimed.

## Resolved or materially improved findings

### CSRF protection — materially improved

`src/sandia/csrf.py:36-48` rejects unsafe requests without a matching per-session token. The app applies it globally in `src/sandia/main.py:88`, while templates add hidden form tokens and HTMX/fetch requests send the header (`src/sandia/templates/base.html:61`, `:398`). The token is rotated after login (`src/sandia/routers/auth.py:47-50`). Tests cover missing, invalid, valid, HTMX, JSON, login, rotation, and template propagation (`tests/test_csrf.py`).

Residual recommendation: add `Origin`/`Referer` validation as defense in depth and verify that any future non-browser API authentication scheme is not accidentally exempted from CSRF policy.

### Session cookie configuration — materially improved

`src/sandia/main.py:106-112` explicitly sets `session_cookie="sandia_session"`, `same_site="lax"`, and `https_only=settings.enable_https`. `src/sandia/config.py:24-32` defaults plain HTTP to `127.0.0.1`. Tests assert the HTTPS and HTTP cookie behavior (`tests/test_routes.py:16-43`).

Residual recommendation: document that setting `SANDIA_HOST` to a non-loopback address while disabling HTTPS intentionally exposes credentials over HTTP. Consider refusing that combination unless an explicit unsafe override is provided.

### Initial administrator credential — improved but not fully closed

Real installs now generate a random password (`src/sandia/main.py:64-72`) and save it with mode `0600`; dummy mode deliberately uses `admin/admin` (`:64-66`). The random password is printed to stdout and remains valid until manually changed/deleted.

Residual recommendation: require a forced password change on first login, make the initial-password artifact one-time or automatically remove it after successful change, and ensure service logs are treated as secret-bearing. Keep dummy mode bound to loopback or clearly require an explicit unsafe exposure override.

## Current findings

### High risk

#### SEC-R1 — Administrator-controlled Ollama URL enables SSRF and data export

**Impact:** The server makes outbound requests to any syntactically valid HTTP/HTTPS host selected in the AI settings. This can reach internal services, link-local/cloud metadata endpoints, or attacker-controlled infrastructure. When chat is used, the request includes DHCP configuration, active lease metadata, service status, and recent DHCP logs.

**Evidence:** URL validation only checks scheme, hostname, and port (`src/sandia/ai.py:54-69`). Server-side requests are made by `list_models()` and `chat_stream()` (`src/sandia/ai.py:72-76`, `:126-151`). The data snapshot is assembled in `src/sandia/ai.py:85-112`. The model-list endpoint also performs an outbound request from a GET route (`src/sandia/routers/ai.py:65-84`).

**Recommendation:** Define an explicit destination policy. Prefer loopback or an allowlist of configured Ollama hosts. Resolve destinations before connecting and reject loopback/private/link-local/multicast/metadata ranges unless explicitly allowed; protect against DNS rebinding and redirects. Set `follow_redirects=False`, bound response size and model/history lengths, limit concurrent chats, and present a clear data-disclosure warning.

### Medium risk

#### SEC-R2 — No explicit browser security headers or CSP

**Impact:** A future template/dependency mistake or compromised third-party asset has a larger authenticated-browser impact. The base template loads Tailwind, fonts, and HTMX from external CDNs without visible SRI, and includes inline scripts (`src/sandia/templates/base.html:7-11`, `:38`, `:312-432`).

**Recommendation:** Add response headers including a deliberate CSP, `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, restrictive `Referrer-Policy`, and an appropriate `Permissions-Policy`. Self-host assets or pin them with SRI. Gradually replace inline scripts with nonces/hashes or external files. Add header regression tests.

#### SEC-R3 — Configuration apply uses shared predictable files without locking or symlink defenses

**Impact:** Concurrent operators/requests can overwrite each other's staged configuration or validate one request and install another. The fixed staging and temporary names also increase risk if an attacker can write to the target directory or manipulate symlinks while the privileged process runs.

**Evidence:** `stage()` overwrites the fixed staging path (`src/sandia/dhcpd/apply.py:43-45`); `_replace_atomically()` uses a fixed sibling `*.sandia-tmp` file and `shutil.copyfile()` before `os.replace()` (`:66-73`). `apply_new_config()` has no application lock around stage/check/install/restart (`:109-143`).

**Recommendation:** Serialize apply/restore operations with an application or file lock. Use securely created per-operation temporary files in the target directory, exclusive creation, ownership/mode checks, and symlink rejection. Bind validation to the exact temporary file being installed. Keep the web process least-privileged and delegate only required DHCP/systemd actions to a narrowly scoped helper or policy.

#### SEC-R4 — Login throttling is process-local and keyed only by username

**Impact:** Restarting the process or using multiple workers bypasses throttling. An attacker can also deliberately lock out a known account for five minutes. The in-memory dictionary has no explicit global bound.

**Evidence:** `src/sandia/rate_limit.py:1-7` documents the process-local design; `:16-38` stores failures only by username. Login calls it with the normalized username (`src/sandia/routers/auth.py:34-43`).

**Recommendation:** Add bounded per-source and per-account controls, preferably through a shared store or reverse proxy. Use backoff rather than an easy account-wide lockout, cap memory, and alert on repeated failures.

#### SEC-R5 — Initial password and operational logs need a stronger lifecycle

**Impact:** The random bootstrap password is stored in plaintext at `<data dir>/initial-admin-password` and printed to stdout (`src/sandia/main.py:68-79`). Anyone with access to service logs or the data directory can authenticate until the password is changed. There is no enforced first-login rotation.

**Recommendation:** Make first login require a password change, delete or invalidate the bootstrap artifact after success, avoid printing the secret in long-lived service logs, and verify parent-directory ownership/mode. Treat backups and logs as credential-bearing during the bootstrap window.

#### SEC-R6 — AI request/resource limits are incomplete

**Impact:** Chat message content is not size-limited before being forwarded, model output can stream for up to five minutes, and there is no visible per-user/concurrent chat limit. A user can consume application connections and outbound Ollama resources.

**Evidence:** `ChatRequest.messages` is an unconstrained list (`src/sandia/routers/ai.py:27-28`); `clean_history()` caps message count but not content length (`src/sandia/ai.py:115-123`); streaming uses a 300-second read timeout (`:132-134`).

**Recommendation:** Enforce maximum message count, per-message and total byte limits at validation time, bound output bytes/tokens, add per-user concurrency/rate limits, and cancel upstream work when the client disconnects.

### Low / operational risk

#### SEC-R7 — Audit and backup data requires explicit retention and access controls

**Impact:** Audit entries, backups, DHCP configuration, lease data, and logs can contain sensitive network inventory. The SQLite audit store and backup retention policy are not visibly bounded or tamper-evident.

**Evidence:** Audit details are stored directly (`src/sandia/audit.py:7-16`), and configuration apply creates timestamped backups without visible retention (`src/sandia/dhcpd/apply.py:83-94`).

**Recommendation:** Define retention/rotation, redact unnecessary data, enforce database and backup ownership/modes, restrict audit access, bound detail lengths, and optionally forward high-value events to an append-only system log.

#### SEC-R8 — Dependency and CDN supply-chain assurance is not demonstrated

**Impact:** The review did not include a vulnerability scan of Python dependencies, and browser assets are retrieved from third-party CDNs at runtime.

**Recommendation:** Add automated lockfile/dependency vulnerability scanning in CI, review/update dependencies regularly, and self-host or integrity-pin runtime browser assets.

## Positive controls observed

- Argon2 password hashing is used (`src/sandia/security.py:10-24`).
- Role checks are centralized and applied to privileged routes (`src/sandia/security.py:44-52`).
- Subprocesses use argument-separated execution, not shell interpolation (`src/sandia/dhcpd/apply.py:32-40`).
- Configuration validation precedes installation and rollback is attempted after restart failure (`src/sandia/dhcpd/apply.py:109-143`).
- Backup restoration rejects path separators and requires a regular file (`src/sandia/routers/backups.py:37-42`).
- CSRF tests cover the main browser request forms and JSON/HTMX paths (`tests/test_csrf.py`).
- TLS private keys and session/bootstrap secrets are created with restrictive file modes (`src/sandia/tls.py:44-52`, `src/sandia/main.py:49-56`, `:69-71`).

## Prioritized to-do list

### Immediate

- [ ] Restrict Ollama destinations, block sensitive address ranges and DNS-rebinding/redirect paths, and document the data-export boundary.
- [ ] Add security headers/CSP and remove or integrity-pin third-party runtime assets.
- [ ] Add a lock and secure per-operation temporary files for DHCP configuration apply/restore.
- [ ] Enforce first-login password rotation and remove the initial-password artifact after use.

### High priority

- [ ] Add AI request-size, output-size, timeout, concurrency, and per-user rate limits.
- [ ] Replace username-only in-memory login throttling with bounded per-IP/per-account controls.
- [ ] Add tests for SSRF destination policy, redirects, DNS rebinding, CSP/header behavior, concurrent apply, symlink defenses, bootstrap rotation, and AI limits.
- [ ] Add dependency vulnerability scanning and runtime asset integrity checks to CI.

### Operational

- [ ] Define audit/database/backup permissions, retention, rotation, redaction, and monitoring.
- [ ] Document secure deployment combinations for HTTPS, `SANDIA_HOST`, reverse proxies, service accounts, and firewalling.
- [ ] Diagnose the pytest stall and make the complete security regression suite a release gate.

## Overall conclusion

The recent changes materially reduce the previously identified authentication and request-forgery risk. CSRF coverage and cookie configuration are now substantially better, and real installs no longer use a fixed admin password. The remaining high-priority concern is the unrestricted outbound AI integration and the fact that the application performs privileged filesystem/service operations. Until those boundaries are restricted and tested, deploy only behind a trusted network boundary with least-privilege host permissions and carefully controlled egress.
