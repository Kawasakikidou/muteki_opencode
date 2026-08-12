"""Coverage for Result + tiered artifact peek (§6.3)."""

from pathlib import Path

from muteki.solver.peek import ArtifactStore, peek
from muteki.solver.result import Result


def test_result_output_sets_success_from_flag() -> None:
    r = Result.output(flag="flag{x}", evidence="solved via decode")
    assert r.success is True
    assert r.flag == "flag{x}"
    r2 = Result.output(evidence="no luck", next_hint="try base64")
    assert r2.success is False


def test_result_for_model_is_compact_and_mentions_peek() -> None:
    r = Result.output(
        evidence="dumped 5000 lines",
        artifact_id="abc123",
        next_hint="search for flag",
        rows=5000,
    )
    txt = r.for_model()
    assert "evidence: dumped 5000 lines" in txt
    assert "abc123" in txt
    assert "peek(" in txt
    assert "next: search for flag" in txt


def test_artifact_store_put_and_peek_paging(tmp_path: Path) -> None:
    store = ArtifactStore(root=tmp_path)
    big = "\n".join(f"line {i}" for i in range(1000))
    aid = store.put(big)
    # page from start
    p = peek(store, aid, lines=10, start=0)
    assert p.found and p.total_lines == 1000 and p.shown_lines == 10
    assert p.content.splitlines()[0] == "line 0"
    # page deeper
    p2 = peek(store, aid, lines=5, start=500)
    assert p2.content.splitlines()[0] == "line 500"


def test_peek_query_centers_on_match(tmp_path: Path) -> None:
    store = ArtifactStore(root=tmp_path)
    lines = [f"noise {i}" for i in range(200)]
    lines[123] = "the flag is flag{deep_inside}"
    aid = store.put("\n".join(lines))
    p = peek(store, aid, query=r"flag\{", lines=10)
    assert p.matched is True
    assert "flag{deep_inside}" in p.content
    assert p.shown_lines <= 10


def test_peek_missing_artifact(tmp_path: Path) -> None:
    store = ArtifactStore(root=tmp_path)
    p = peek(store, "doesnotexist")
    assert p.found is False


def test_peek_query_no_match(tmp_path: Path) -> None:
    store = ArtifactStore(root=tmp_path)
    aid = store.put("nothing here\nor here")
    p = peek(store, aid, query="flag")
    assert p.found is True and p.matched is False


def test_peek_rejects_path_traversal_artifact_id(tmp_path: Path) -> None:
    # F27: a model-controlled artifact_id must never escape the store root —
    # ../../ style ids resolve to "not found", not an arbitrary file read.
    store = ArtifactStore(root=tmp_path)
    aid = store.put("secret")
    for evil in ("../x", "..\\x", "*", "../../shared_graph.db", "aid;"):
        p = peek(store, evil)
        assert p.found is False, evil
    # canonical id still resolves
    assert peek(store, aid).found is True


def test_peek_tolerates_invalid_regex(tmp_path: Path) -> None:
    # F28: an invalid model-supplied regex must degrade, not raise.
    store = ArtifactStore(root=tmp_path)
    aid = store.put("alpha beta gamma")
    p = peek(store, aid, query="(unclosed")
    assert p.found is True and p.matched is False


def test_peek_refuses_catastrophic_backtracking_regex(tmp_path: Path) -> None:
    # Round-5: `(a+)+` / `(a|ab)+$` / `(\w+\s*)+` are the exponential-backtracking
    # shapes — a model-controlled query must degrade to "no match" instantly,
    # never hang the worker. The 200-char cap alone does NOT stop these.
    store = ArtifactStore(root=tmp_path)
    aid = store.put("a" * 100_000)  # a long line that would trigger the blowup
    for evil in (r"(a+)+", r"(a|ab)+$", r"(\w+\s*)+", r"([0-9]+)+", r"(a|b)+"):
        p = peek(store, aid, query=evil)
        assert p.found is True and p.matched is False, evil


def test_peek_skips_oversized_lines_when_searching(tmp_path: Path) -> None:
    # Round-5: even a benign regex scanning a single >64 KiB line is quadratic
    # on `.*`-style scans — such lines are excluded from matching (content that
    # big can't be shown in a peek anyway).
    store = ArtifactStore(root=tmp_path)
    aid = store.put(("x" * 200_000) + "\nflag{on_short_line}")
    p = peek(store, aid, query="flag")
    assert p.found is True and p.matched is True
    assert "flag{on_short_line}" in p.content


def test_peek_benign_regexes_still_match(tmp_path: Path) -> None:
    # Round-5: the ReDoS heuristic must not reject ordinary search patterns.
    store = ArtifactStore(root=tmp_path)
    aid = store.put("host 10.0.0.1 port 8080")
    for ok in (r"\d+\.\d+\.\d+\.\d+", r"flag\{[0-9a-f]{32}\}", r"[A-Za-z]+ \d+",
               r"(\d{4})-(\d{2})", r"cat|dog", r"a+b+"):
        p = peek(store, aid, query=ok)
        assert p.found is True, ok
