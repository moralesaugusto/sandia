from sandia import rate_limit


def test_not_locked_before_max_attempts():
    key = "user-a"
    rate_limit.clear_failures(key)
    for _ in range(rate_limit.MAX_ATTEMPTS - 1):
        rate_limit.record_failure(key)
    assert rate_limit.seconds_locked(key) == 0.0


def test_locked_after_max_attempts():
    key = "user-b"
    rate_limit.clear_failures(key)
    for _ in range(rate_limit.MAX_ATTEMPTS):
        rate_limit.record_failure(key)
    assert rate_limit.seconds_locked(key) > 0.0


def test_clear_failures_resets_lock():
    key = "user-c"
    rate_limit.clear_failures(key)
    for _ in range(rate_limit.MAX_ATTEMPTS):
        rate_limit.record_failure(key)
    assert rate_limit.seconds_locked(key) > 0.0

    rate_limit.clear_failures(key)
    assert rate_limit.seconds_locked(key) == 0.0


def test_old_failures_outside_window_do_not_count(monkeypatch):
    key = "user-d"
    rate_limit.clear_failures(key)
    current_time = [0.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: current_time[0])

    for _ in range(rate_limit.MAX_ATTEMPTS - 1):
        rate_limit.record_failure(key)

    current_time[0] = rate_limit.WINDOW_SECONDS + 10
    rate_limit.record_failure(key)  # only this one attempt is still within the window

    assert rate_limit.seconds_locked(key) == 0.0
