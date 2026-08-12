"""SessionStore JSONL durability + run_id path guards (H1b).

H1b: `_path` used to be a replace-only sanitizer — on Windows a drive-qualified
id (`C:\\evil`) or UNC id (`\\\\server\\share`) kept the WHOLE rhs of
`root / id.jsonl` and escaped sessions_root entirely (arbitrary JSONL read via
replay, arbitrary append via the bus sink). The guard must be rejection-based
and platform-independent (pure string checks — a `\\` or drive prefix is
poisonous on every OS, not just Windows).
"""

from __future__ import annotations

import asyncio

import pytest

from muteki.core.events import Event, EventType
from muteki.core.session_store import SessionStore

_BAD_RUN_IDS = [
    "C:\\evil",
    "C:evil",           # drive-relative — escape on Windows
    "\\\\server\\share\\x",
    "a\\b",             # backslash separator (Windows)
    "..",
    ".",
    "",
    None,
    "x\x00y",           # NUL
    "..\\..\\etc\\passwd",
    "a..b",             # Round-5: `..` substring — folds to a_b (collides)
    "run..1",
    "a...b",
]


@pytest.mark.parametrize("run_id", _BAD_RUN_IDS)
def test_path_rejects_escaping_run_ids(tmp_path, run_id):
    store = SessionStore(root=tmp_path)
    with pytest.raises(ValueError):
        store.path_for(run_id)  # type: ignore[arg-type]


def test_path_keeps_forward_slash_replacement(tmp_path):
    """batch challenge ids like 'web/xss' are legitimate — forward slashes keep
    the historical `_` replacement instead of being rejected."""
    store = SessionStore(root=tmp_path)
    p = store.path_for("batch-web/xss")
    assert p.name == "batch-web_xss.jsonl"
    assert p.parent == tmp_path


def test_path_accepts_legitimate_ids(tmp_path):
    store = SessionStore(root=tmp_path)
    for rid in ("run-0001", "run-0001-r2", "batch-17", "a.b_c-d", "uuid-like-1234"):
        p = store.path_for(rid)
        assert p.parent == tmp_path
        assert p.name == f"{rid}.jsonl"


def test_path_single_dot_inside_id_kept_distinct(tmp_path):
    """Round-5: a SINGLE dot inside the id must stay itself (`a.b` ≠ `a_b`) —
    only a `..` SUBSTRING is the collision hazard."""
    store = SessionStore(root=tmp_path)
    assert store.path_for("a.b").name == "a.b.jsonl"
    assert store.path_for("a_b").name == "a_b.jsonl"
    assert store.path_for("a.b") != store.path_for("a_b")


def test_path_rejects_dotdot_substring(tmp_path):
    """Round-5: `a..b` used to fold to `a_b` — the SAME jsonl as the distinct
    run `a_b`, so replay/SSE mixed the two runs' events (incl. flags)."""
    store = SessionStore(root=tmp_path)
    for rid in ("a..b", "run..1", "a...b", "..x", "x.."):
        with pytest.raises(ValueError):
            store.path_for(rid)


def test_append_rejects_escaping_run_id(tmp_path):
    store = SessionStore(root=tmp_path)
    ev = Event(event_type=EventType.RUN_STARTED, run_id="C:\\evil", payload={})
    with pytest.raises(ValueError):
        asyncio.run(store.append(ev))


def test_replay_rejects_escaping_run_id(tmp_path):
    store = SessionStore(root=tmp_path)
    gen = store.replay("\\\\server\\share\\x")
    # replay is an async generator — the _path guard fires on first iteration.
    with pytest.raises(ValueError):
        asyncio.run(gen.__anext__())


def test_lock_table_is_bounded(tmp_path):
    """Round-5: _locks must not grow without bound on a long-lived backend —
    evicts a non-held lock first, else the oldest-inserted entry."""
    store = SessionStore(root=tmp_path)
    store._MAX_LOCKS = 3
    for i in range(5):
        store._lock_for(f"run-{i:03d}")
    assert len(store._locks) <= 3
    # oldest-inserted entries were evicted first (all locks were idle)
    assert "run-000" not in store._locks
    assert "run-004" in store._locks


def test_lock_table_evicts_idle_before_held(tmp_path):
    """Round-5: when the table is full, an idle lock is evicted in preference to
    a held one."""
    async def _scenario():
        store = SessionStore(root=tmp_path)
        store._MAX_LOCKS = 2
        held = store._lock_for("held")
        await held.acquire()            # hold it
        assert held.locked() is True
        store._lock_for("idle-1")       # {held(locked), idle-1}
        store._lock_for("idle-2")       # evicts idle-1 (unlocked) → {held, idle-2}
        assert "held" in store._locks   # held lock survived
        assert "idle-1" not in store._locks
        held.release()

    asyncio.run(_scenario())
