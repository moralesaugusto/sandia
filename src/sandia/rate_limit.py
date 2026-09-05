"""In-memory login attempt throttling.

Deliberately simple and process-local (resets on restart) - this is a
standalone, single-process app run by one operator, not a distributed
service, so a persistent/shared store would be over-engineering. Keyed by
username: enough to stop a brute-force run against one account without
needing per-IP tracking.
"""

import time

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300
LOCKOUT_SECONDS = 300

_failures: dict[str, list[float]] = {}


def record_failure(key: str) -> None:
    now = time.monotonic()
    attempts = [t for t in _failures.get(key, []) if now - t < WINDOW_SECONDS]
    attempts.append(now)
    _failures[key] = attempts


def clear_failures(key: str) -> None:
    _failures.pop(key, None)


def seconds_locked(key: str) -> float:
    """Remaining lockout in seconds, 0 if not currently locked."""
    now = time.monotonic()
    attempts = [t for t in _failures.get(key, []) if now - t < WINDOW_SECONDS]
    _failures[key] = attempts
    if len(attempts) < MAX_ATTEMPTS:
        return 0.0
    remaining = LOCKOUT_SECONDS - (now - attempts[-1])
    return max(0.0, remaining)
