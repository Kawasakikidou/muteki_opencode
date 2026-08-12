"""Durable event log — append every event to JSONL (one file per run), replay later.

This is what makes "replay any challenge's full solve after the match" work.
It registers as a sink on the EventBus so persistence is automatic.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import AsyncIterator

from muteki.core.events import Event


_REPLAY_YIELD_EVERY = 100


class SessionStore:
    def __init__(self, root: str | Path = "sessions") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # Per-run append locks. Bounded (Round-5): a long-lived backend that saw
        # thousands of distinct run ids would grow this dict forever — a finished
        # run's lock is dead weight. On insert, if the table exceeds _MAX_LOCKS,
        # evict an idle (non-held) entry first, else the oldest-inserted one.
        self._locks: dict[str, asyncio.Lock] = {}
        self._MAX_LOCKS = 512

    def _path(self, run_id: str) -> Path:
        # H1b: REJECT — never sanitize — ids that could reach outside root on
        # ANY platform. The old replace-only guard never touched `\` or drive
        # prefixes: on Windows `root / "C:\\evil.jsonl"` keeps the WHOLE rhs
        # (drive-qualified) and `\\server\share\x.jsonl` escapes via UNC —
        # arbitrary JSONL read through replay(), arbitrary append through the
        # bus sink. `..` / `.` / empty are rejected outright — and a `..`
        # SUBSTRING too (Round-5: folding `a..b`→`a_b` collides two distinct
        # run ids onto one jsonl); forward slashes keep the historical `_`
        # replacement (batch challenge ids like "web/xss" are legitimate run
        # ids). Raises ValueError — callers translate to 400 / skip, never
        # fall through to a filesystem path.
        s = str(run_id or "")
        if not s or s in (".", "..") or ".." in s:
            # Round-5: a `..` SUBSTRING (e.g. `a..b`) must be rejected, not
            # replaced — folding it to `a_b` collides with the real `a_b` run
            # id (two runs, one jsonl file, cross-contaminated event streams).
            # The web whitelist (_RUN_ID_SAFE) already refuses `..`; this keeps
            # direct callers (batch runner) on the same rule.
            raise ValueError(f"unsafe run_id: {run_id!r}")
        if "\\" in s or "\x00" in s:
            raise ValueError(f"unsafe run_id: {run_id!r}")
        if re.match(r"^[A-Za-z]:", s):  # drive prefix (C:evil is drive-relative on Windows)
            raise ValueError(f"unsafe run_id: {run_id!r}")
        safe = s.replace("/", "_")
        return self.root / f"{safe}.jsonl"

    def path_for(self, run_id: str) -> Path:
        """Public path helper — lets callers report/peek a run's events file
        without reaching into the private `_path` (batch runner uses it)."""
        return self._path(run_id)

    def _lock_for(self, run_id: str) -> asyncio.Lock:
        lock = self._locks.get(run_id)
        if lock is not None:
            return lock
        if len(self._locks) >= self._MAX_LOCKS:
            # evict any non-held lock first; if all are held, drop the oldest
            # anyway (an append lock is a correctness nicety — worst case two
            # appends to one file serialize in the OS instead)
            for rid, lk in list(self._locks.items()):
                if not lk.locked():
                    del self._locks[rid]
                    break
            else:
                del self._locks[next(iter(self._locks))]
        lock = asyncio.Lock()
        self._locks[run_id] = lock
        return lock

    async def append(self, event: Event) -> None:
        path = self._path(event.run_id)
        line = event.model_dump_json() + "\n"
        async with self._lock_for(event.run_id):
            # Synchronous append under an async lock; writes are small and the
            # OS buffers them. Keeps ordering per run without a thread pool.
            with path.open("a", encoding="utf-8") as f:
                f.write(line)

    # EventBus sink signature
    async def sink(self, event: Event) -> None:
        await self.append(event)

    async def replay(self, run_id: str) -> AsyncIterator[Event]:
        path = self._path(run_id)
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as f:
            n = 0
            for raw in f:
                raw = raw.strip()
                if raw:
                    n += 1
                    yield Event.model_validate_json(raw)
                    if n % _REPLAY_YIELD_EVERY == 0:
                        # Historical SSE subscribers can replay tens of thousands
                        # of JSONL events. Cooperate with the uvicorn loop so
                        # unrelated API calls do not look globally frozen.
                        await asyncio.sleep(0)

    def last_stream_seq(self, run_id: str) -> int:
        """Return the monotonic SSE sequence after normalizing persisted history.

        Old runs can contain a sequence reset after a backend restart/reopen
        (for example 1808, then 1). Raw max(seq) is not enough in that case:
        the browser's Last-Event-ID is a stream cursor, so future buses must
        continue after the normalized cursor, not after the raw max.
        """
        path = self._path(run_id)
        if not path.exists():
            return 0
        seq = 0
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                raw_seq = int(ev.get("seq") or 0)
                seq = max(seq + 1, raw_seq)
        return seq

    async def replay_monotonic(
        self, run_id: str, *, after_seq: int = 0
    ) -> AsyncIterator[Event]:
        """Replay durable history with a strictly increasing stream seq.

        The event payload remains unchanged, but `event.seq` is rewritten for
        transport/reducer identity if a persisted segment reset its raw seq.
        This repairs existing corrupted JSONL without rewriting the file.
        """
        stream_seq = 0
        n = 0
        async for ev in self.replay(run_id):
            raw_seq = int(ev.seq or 0)
            stream_seq = max(stream_seq + 1, raw_seq)
            if stream_seq <= after_seq:
                continue
            n += 1
            if stream_seq != ev.seq:
                ev = ev.model_copy(update={"seq": stream_seq})
            yield ev
            if n % _REPLAY_YIELD_EVERY == 0:
                await asyncio.sleep(0)

    def list_runs(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.jsonl"))

    def load_all(self, run_id: str) -> list[dict]:
        """Sync convenience for tests / frontends: full event dicts for a run."""
        path = self._path(run_id)
        if not path.exists():
            return []
        out = []
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if raw:
                    out.append(json.loads(raw))
        return out

    def summary(self, run_id: str) -> dict:
        """Cheap one-run digest for the deck's thread rail (name/category/won/flag).

        Scans the persisted JSONL without reconstructing deck state — pulls the
        challenge identity from run.started and the verdict from run.finished /
        the FlagFound insight. Returns zeros for a run with no events yet.

        Multi-flag aware: carries flags(list)/expected_flags/multi_flag through so a
        rehydrated multi-flag run isn't flattened to a single-flag look-alike. `solved`
        is computed by MODE:
          - single-flag (or mode unknown): a FlagFound is enough to mark solved — this
            keeps the "ghost run" fallback (FlagFound but no RUN_FINISHED → still
            shows solved after restart);
          - multi-flag PARTIAL (collected < expected): a FlagFound does NOT mark solved
            (one of three flags is not a win).
        run.finished's explicit `solved` always wins (it knows the real verdict).
        """
        path = self._path(run_id)
        summary = {
            "run_id": run_id, "name": run_id, "category": "",
            "started": False, "finished": False, "solved": False, "flag": None,
            "flags": [], "expected_flags": 1, "multi_flag": False,
            "events": 0, "ts": 0.0,
        }
        if not path.exists():
            return summary

        flags: list[str] = []  # de-duped, order-preserved collected flags

        def _add_flag(val) -> None:
            for f in (val if isinstance(val, list) else [val]):
                if f and f not in flags:
                    flags.append(f)

        finished_solved: bool | None = None  # explicit verdict from run.finished

        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                summary["events"] += 1
                summary["ts"] = ev.get("ts", summary["ts"]) or summary["ts"]
                et = ev.get("event_type")
                p = ev.get("payload") or {}
                if et == "run.started":
                    summary["started"] = True
                    ch = p.get("challenge") or {}
                    summary["name"] = ch.get("name") or summary["name"]
                    summary["category"] = ch.get("category") or summary["category"]
                    if ch.get("expected_flags"):
                        summary["expected_flags"] = int(ch["expected_flags"])
                    if "multi_flag" in ch:
                        summary["multi_flag"] = bool(ch["multi_flag"])
                elif et == "run.titled":
                    # ChatGPT-style auto-title persisted on the run — survives restart
                    summary["name"] = p.get("title") or summary["name"]
                elif et == "run.finished":
                    summary["finished"] = True
                    finished_solved = bool(p.get("solved"))
                    _add_flag(p.get("flags") or p.get("flag"))
                    # run.finished may carry the authoritative mode (the single-solver
                    # _emit_finished does not — default fallbacks above cover that).
                    if p.get("expected_flags"):
                        summary["expected_flags"] = int(p["expected_flags"])
                    if "multi_flag" in p:
                        summary["multi_flag"] = bool(p["multi_flag"])
                elif et == "run.reopened":
                    summary["finished"] = False
                    finished_solved = False
                    if p.get("reason") == "resolve":
                        continue
                    bad = p.get("flag")
                    if bad:
                        flags[:] = [f for f in flags if f != bad]
                    else:
                        flags.clear()
                elif et == "insight.event" and p.get("kind") == "FlagFound":
                    _add_flag(p.get("flag"))

        summary["flags"] = flags
        summary["flag"] = flags[0] if flags else None

        # ── verdict, by mode ────────────────────────────────────────────────
        if finished_solved is not None:
            summary["solved"] = finished_solved  # explicit verdict wins
        elif flags:
            # no RUN_FINISHED on disk (ghost run) but flags were found. Single-flag /
            # unknown-mode: a found flag is a win. Multi-flag: only a win once the
            # full set is collected (partial ≠ solved).
            if summary["multi_flag"]:
                summary["solved"] = len(flags) >= summary["expected_flags"]
            else:
                summary["solved"] = True
        return summary

    def summaries(self) -> list[dict]:
        """All persisted runs, newest-activity first — feeds the rail's Recent."""
        out = [self.summary(rid) for rid in self.list_runs()]
        out.sort(key=lambda s: s.get("ts", 0.0), reverse=True)
        return out
