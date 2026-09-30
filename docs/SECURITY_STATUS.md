# Security Status

Tracks the findings of the security review dated 2026-09-30
(`securityreview2026-09-30.md`, kept unchanged as the original record).
Last updated 2026-09-30.

| ID | Finding | Risk | Status | Note |
|---|---|---|---|---|
| SEC-01 | Known default admin credentials | Critical | In progress | A real install gets a random admin password, printed once and saved to `<data dir>/initial-admin-password` (0600). Dummy mode keeps `admin` / `admin`. |
| SEC-02 | No CSRF protection | High | In progress | Per-session token checked on every non-GET request (form field or `X-CSRF-Token` header, covering htmx and `/ai/chat`), rotated on login. |
| SEC-03 | Session cookie not hardened | High | In progress | `sandia_session`, HttpOnly, SameSite=Lax, Secure when HTTPS is on; plain HTTP binds to 127.0.0.1 by default. |
| SEC-04 | Unrestricted Ollama URL (SSRF, data export) | High | Planned | Restrict destinations, block link-local/metadata ranges and redirects. |
| SEC-05 | No security headers or CSP; CDN assets without SRI | Medium | Planned | Add headers and a CSP; self-host or SRI-pin Tailwind, htmx and fonts. |
| SEC-06 | Login throttling is in-memory and keyed by username only | Medium | Planned | Add per-IP limits and bound memory; stop account lockout by strangers. |
| SEC-07 | Predictable staging path, no apply lock | Medium | Planned | Per-apply temp file, a lock around apply, symlink/ownership checks. |
| SEC-08 | Audit log sensitivity and unbounded growth | Medium | Planned | Retention, redaction and file permissions for the database and backups. |

No finding is currently accepted as a risk.
