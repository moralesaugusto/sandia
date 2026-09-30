Read CLAUDE.md, README.md, docs/ (including the Codex security review dated 2026-09-30), CHANGELOG.md and INSTRUCTIONS.md. I am preparing to publish this repo over the Internet, so the goal is to make it accurate, consistent and safe to share. I fixed SEC-01 (default admin credentials) and SEC-03 (session cookie hardening) myself. Do not modify, revert or overwrite those changes. Run git status and git diff first so you know what is in progress, and work around it. Work through the phases below in order, verify each one, and keep changes small.

Phase 1: Verify the facts
- Run the full test suite to completion with a per-test timeout. The Codex review says pytest stalled after 15 tests. Find the root cause of any hang and fix it. Report the real pass count.
- Check each claim in README.md against the code (HTTPS by default, login rate limiting, "private by design", bind address). List any claim that is overstated. Ignore the admin/admin text and cookie claims for now, since I am changing those.

Phase 2: Fix SEC-02 (CSRF)
- Add CSRF protection for every state-changing request, including htmx requests and /ai/chat, using a per-session token validated server-side, sent as a form field or custom header.
- Make sure it works with the cookie settings I am adding for SEC-03 (same_site, https_only) and does not conflict with them.
- Add regression tests for a missing token, an invalid token and a valid token.
- Do not touch SEC-04 to SEC-08 beyond recording their status.

Phase 3: Clean up the docs
- Replace "this pass" wording in docs/CURRENT_STATE.md and docs/ROADMAP.md with version numbers or dates taken from CHANGELOG.md.
- Fix stale or contradictory lines (the utilization bar versus SVG map note, "dependency-light script", "both gaps" versus three listed, test counts). Move Phases 5 and 6 above "Later / not scheduled" in ROADMAP.md.
- Add docs/SECURITY_STATUS.md listing SEC-01 to SEC-08 with a status for each (fixed, in progress, planned, accepted risk) and a one-line note. Mark SEC-01 and SEC-03 as in progress until I confirm they are done. Keep the original Codex report unchanged as a dated record.
- Reconcile CURRENT_STATE.md (instructions described features that did not exist) with CLAUDE.md calling this an existing application. Check the git history for what was inherited versus built, and write the docs to match the facts. Do not guess.

Phase 4: Privacy check before publishing
- Open every image in screenshots/ and report any visible real MAC, IP, hostname, username or vendor detail that could identify a private network.
- Search the current tree and the git history for secrets, real IP or MAC addresses, tokens or private keys. Report findings only. Do not rewrite history or force-push.

Phase 5: Repo polish
- Propose a better GitHub About description and topics. Do not change remote settings.

Rules: no emojis anywhere, keep documentation minimal, do not claim something works without running it, and do not commit until you show me a summary of the diff. When finished, give me a short report listing what you changed, what you could not verify, and anything you think still blocks publishing.