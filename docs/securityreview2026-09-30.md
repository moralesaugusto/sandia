# Sandia Security Review — 2026-09-30

**Reviewed by:** OpenAI GPT-5 (Codex)

## Scope and method

This review is a static security assessment of the repository as inspected on 2026-09-30. It covers authentication, authorization, session handling, request integrity, privileged file and service operations, integrations, templates, dependencies, and operational defaults.

The review did not include a deployed-environment penetration test, infrastructure review, dependency vulnerability scan, or review of production secrets. The local pytest run was attempted but stalled after 15 tests; therefore, no complete test-suite result is claimed.

## Executive summary

The project has useful security foundations: Argon2 password hashing, role checks on privileged routes, parameterized subprocess execution, atomic configuration replacement, audit logging, and path traversal checks for backup restoration.

The most important risks are request-forgery protection and first-run authentication. Every state-changing form/API endpoint appears to accept requests without a CSRF token, while the application creates a known `admin/admin` account on first startup. If the application is reachable by other users, either issue can lead to unauthorized configuration changes or full administrative takeover. Session cookie hardening and deployment headers also need improvement before exposing the service beyond a trusted host or reverse proxy.

## Findings by risk

### Critical

#### SEC-01 — Known default administrator credentials

**Impact:** Full administrative takeover on an uninitialized deployment.

**Evidence:** `src/sandia/main.py:59-68` creates an administrator with the fixed password `admin` and prints the credentials. The application binds to `0.0.0.0` by default in `src/sandia/config.py:24`.

**Why it matters:** A fresh instance exposed on a network can be logged into immediately with publicly guessable credentials. An admin can create users, change settings, apply DHCP configuration, and control the service.

**Recommendation:** Do not create a usable account with a fixed password. Require an explicit first-run bootstrap secret, an interactive password setup, or a one-time setup token bound to localhost. Refuse non-loopback startup until setup is complete, or require an explicit override. Add a test that a fresh deployment cannot authenticate with a known default password.

### High

#### SEC-02 — Missing CSRF protection on state-changing requests

**Impact:** A logged-in user can be induced to submit actions from a malicious page. Depending on the victim’s role, this can change DHCP configuration, restart/enable/disable the service, modify users, alter reservations, restore backups, change passwords, or delete lease data.

**Evidence:** The templates submit POST requests without CSRF tokens, for example `src/sandia/templates/login.html:23-33`, `src/sandia/templates/base.html:154-170,276-278`, and `src/sandia/templates/raw_config.html:7-15`. The routers accept these requests without checking an origin-bound token; representative routes are in `src/sandia/routers/raw_config.py:30-76` and `src/sandia/routers/service.py:39-75`.

**Recommendation:** Add a per-session, cryptographically random CSRF token and validate it on every state-changing browser request, including HTMX and JSON requests. Send the token in a form field or custom header. Also validate `Origin`/`Referer` where practical and use `SameSite=Lax` or stricter as defense in depth. Add regression tests for missing, invalid, and valid tokens.

#### SEC-03 — Session cookie is not explicitly hardened for HTTPS deployments

**Impact:** Session cookies may be sent over plaintext HTTP or be exposed to client-side script if deployment defaults change or traffic is misrouted. The application enables HTTPS by default, but the session middleware is created without explicit `https_only`, `same_site`, or cookie-name settings.

**Evidence:** `src/sandia/main.py:91-94` calls `SessionMiddleware` with only `secret_key`. HTTP is still an explicit supported mode in `src/sandia/main.py:209-215` when `SANDIA_HTTPS=0`.

**Recommendation:** Set `https_only=True` for production HTTPS mode, `same_site="lax"` or `"strict"`, and an explicit secure cookie name. Ensure HTTP redirects to HTTPS or bind HTTP only to loopback. Document the trusted reverse-proxy configuration and add tests asserting cookie attributes.

#### SEC-04 — Server-side requests to administrator-selected Ollama URLs are not network restricted

**Impact:** The server makes outbound HTTP requests to a URL selected by an administrator. This can be used to probe or access internal HTTP services, cloud metadata endpoints, or other network locations from the host running Sandia. Configuration and DHCP/lease/log data are also sent to the selected endpoint.

**Evidence:** `src/sandia/ai.py:54-69` accepts arbitrary `http`/`https` hosts, and `src/sandia/ai.py:72-76,126-135` makes server-side requests. The URL is stored through the admin-only route `src/sandia/routers/ai.py:40-62`.

**Recommendation:** Prefer a local-only Ollama allowlist (`127.0.0.1`, `::1`, and explicitly configured private address ranges) or require an explicit outbound-network policy. Resolve and validate addresses before connecting, block link-local and cloud-metadata ranges, disable redirects, and apply strict connect/read/response-size limits. Treat the integration as a data-export boundary and disclose that configuration/log data is sent to the selected server.

### Medium

#### SEC-05 — No response security headers or Content Security Policy

**Impact:** The application has limited browser-side defense in depth against XSS, clickjacking, MIME confusion, and unsafe third-party script execution. It loads Tailwind and HTMX from public CDNs without integrity attributes.

**Evidence:** `src/sandia/templates/base.html:7-11,38` loads external assets. No security-header middleware or response headers were identified.

**Recommendation:** Add at least `Content-Security-Policy`, `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, and an appropriate `Permissions-Policy`. Self-host or pin third-party assets with SRI and a restrictive CSP. Verify that HTMX fragments cannot inject untrusted markup.

#### SEC-06 — Login throttling is process-local and keyed only by username

**Impact:** Restarting the process clears throttling, multiple workers bypass the shared limit, and a remote attacker can lock out a known account by submitting five invalid attempts for its username.

**Evidence:** `src/sandia/rate_limit.py:1-7,16-37` stores failures in an in-memory dictionary keyed by username.

**Recommendation:** Use a shared bounded store or a reverse-proxy rate limit, combine account and source-IP controls, add an exponential backoff, cap memory growth, and avoid allowing unlimited account-specific denial of service. Preserve generic login errors, as the current route does.

#### SEC-07 — Privileged file operations rely on predictable staging paths and lack concurrency controls

**Impact:** Concurrent operators can overwrite each other’s staged configuration, and deployments that permit an untrusted local user to write the DHCP configuration directory may be exposed to symlink or file-race attacks while the process runs with elevated privileges.

**Evidence:** `src/sandia/config.py:58-66` uses a fixed `.sandia-staged.conf`; `src/sandia/dhcpd/apply.py:43-45,66-73` writes and replaces files without locking or no-follow protections.

**Recommendation:** Use a per-apply temporary file created securely in the target directory, enforce ownership and mode, use an application lock around stage/check/install/restart, reject symlinks for security-sensitive paths, and verify expected ownership before replacement. Consider isolating Sandia with a narrowly scoped service account and policy rather than running the whole web process as root.

#### SEC-08 — Audit log data can contain sensitive operational information and is not protected from unbounded growth

**Impact:** DHCP configuration errors, service output, usernames, and client/network information may accumulate in SQLite. Unbounded growth can consume disk space, and access to the database or audit UI exposes sensitive network inventory.

**Evidence:** `src/sandia/audit.py:7-16` stores request IPs and arbitrary action details; failure paths log command output, for example `src/sandia/routers/raw_config.py:69-71`.

**Recommendation:** Define retention and rotation limits, restrict database and backup permissions, redact secrets and unnecessary client data, paginate and authorize audit access, and add monitoring for storage exhaustion. Document that backups may contain complete DHCP configuration and client information.

## Positive controls observed

- Passwords are hashed with Argon2 in `src/sandia/security.py:10-24`.
- Privileged routes use role dependencies rather than relying only on UI visibility.
- Subprocesses use argument-separated execution rather than shell interpolation in `src/sandia/dhcpd/apply.py:32-40`.
- Configuration installation uses a temporary sibling file and `os.replace` in `src/sandia/dhcpd/apply.py:66-73`.
- Backup restore rejects path separators in the requested filename in `src/sandia/routers/backups.py:37-40`.
- Jinja templates generally use autoescaping, and the AI message renderer uses `textContent` rather than assigning model output as HTML.
- The session secret and TLS private key are written with mode `0600` in `src/sandia/main.py:48-56` and `src/sandia/tls.py:44-52`.

## Prioritized to-do list

### Immediate — before network exposure

- [ ] Remove fixed `admin/admin` bootstrap credentials; implement secure first-run setup.
- [ ] Add CSRF protection to all POST and other state-changing endpoints, including HTMX and `/ai/chat`.
- [ ] Explicitly harden session cookies and require HTTPS for non-loopback deployments.
- [ ] Add security headers and a restrictive CSP; pin or self-host CDN assets.
- [ ] Document and enforce a least-privilege deployment model for privileged DHCP/service operations.

### Next — before production use

- [ ] Restrict and harden outbound Ollama connections; block metadata/link-local destinations and redirects.
- [ ] Add per-IP plus per-account login throttling using a shared or persistent limiter.
- [ ] Add locking, secure temporary-file creation, symlink checks, and ownership/mode validation to configuration apply.
- [ ] Define audit/backup retention, redaction, file permissions, and disk-space monitoring.
- [ ] Add tests for authorization boundaries, CSRF, cookie flags, first-run setup, path traversal, SSRF restrictions, and concurrent apply behavior.

### Ongoing assurance

- [ ] Run the full test suite to completion and investigate the observed stall after 15 tests.
- [ ] Add dependency auditing in CI for the locked Python dependency set.
- [ ] Add a deployment security checklist covering reverse proxies, TLS trust, firewall exposure, service account permissions, backups, and log access.
- [ ] Perform an authenticated web penetration test against a representative deployment.

## Overall risk rating

**High before remediation.** The default credential and missing CSRF defenses can enable complete administrative impact in realistic networked deployments. After those controls are fixed, the remaining risk is primarily deployment-dependent: session/TLS configuration, privileged file handling, outbound AI integration, and protection of network inventory data.
