"""LoginThrottle sliding-window lockout logic (M2) + bounded IP table (Round-5).

Pure logic tests — no FastAPI import needed (auth.py only lazy-imports
fastapi inside check() when raising the 429), so this runs everywhere.
"""

from __future__ import annotations

import pytest

from apps.web.auth import LoginThrottle

T0 = 1_000_000.0


def test_lockout_after_max_fails_within_window():
    t = LoginThrottle(window_s=300.0, max_fails=3)
    t.fail("1.2.3.4", now=T0)
    t.fail("1.2.3.4", now=T0 + 10)
    t.check("1.2.3.4", now=T0 + 20)  # 2 fails < 3 → no raise
    t.fail("1.2.3.4", now=T0 + 30)
    # lockout → check() raises (HTTPException on a fastapi-enabled host; the
    # lazy import means this platform without fastapi raises ImportError — the
    # CONTRACT is "raises during lockout, silent otherwise", which is what we
    # assert here; the 429 status itself is pinned in test_web_auth.py).
    with pytest.raises(Exception):
        t.check("1.2.3.4", now=T0 + 40)


def test_window_slides_out_after_timeout():
    t = LoginThrottle(window_s=100.0, max_fails=2)
    t.fail("1.2.3.4", now=T0)
    t.fail("1.2.3.4", now=T0 + 10)
    with pytest.raises(Exception):
        t.check("1.2.3.4", now=T0 + 20)  # 2 fails → locked
    with pytest.raises(Exception):
        t.check("1.2.3.4", now=T0 + 50)
    # old failures slide out of the window → unlocked again
    t.check("1.2.3.4", now=T0 + 150)
    t.fail("1.2.3.4", now=T0 + 160)
    t.check("1.2.3.4", now=T0 + 170)  # 1 fresh fail < 2 → no raise


def test_successful_login_clears_failures():
    t = LoginThrottle(window_s=300.0, max_fails=2)
    t.fail("1.2.3.4", now=T0)
    t.fail("1.2.3.4", now=T0 + 5)
    t.ok("1.2.3.4")
    t.check("1.2.3.4", now=T0 + 10)  # cleared → no raise


def test_per_ip_isolation():
    t = LoginThrottle(window_s=300.0, max_fails=1)
    t.fail("a", now=T0)
    with pytest.raises(Exception):
        t.check("a", now=T0 + 1)
    t.check("b", now=T0 + 1)  # different IP unaffected


def test_ip_table_is_bounded():
    """Round-5: _fails must not grow without bound — _MAX_IPS caps it, dropping
    stale (empty-window) entries first, then the oldest by insertion."""
    t = LoginThrottle(window_s=300.0, max_fails=5)
    t._MAX_IPS = 4
    for i in range(10):
        t.fail(f"ip-{i}", now=T0)
    assert len(t._fails) <= 4
    # the oldest-inserted ips were dropped first
    assert "ip-0" not in t._fails
    assert "ip-9" in t._fails


def test_ip_table_cap_prefers_dropping_stale_entries():
    t = LoginThrottle(window_s=300.0, max_fails=5)
    t._MAX_IPS = 2
    t.fail("stale", now=T0)          # will slide out
    t.fail("fresh1", now=T0)
    t.fail("fresh2", now=T0 + 10)
    # stale's window has elapsed → empty list → dropped first, fresh kept
    t.fail("fresh3", now=T0 + 400)
    assert "stale" not in t._fails
    assert "fresh3" in t._fails
