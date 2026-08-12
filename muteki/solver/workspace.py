"""Run workspace materialization: immutable inputs, shared CAS, and manifest.

The workspace protocol is intentionally local-filesystem only.  Both host-local
workers and container workers see the same layout under ``sessions/<run>/workspace``:
inputs are content-addressed, shared artifacts are content-addressed, and worker
directories only contain relative symlinks into those stable locations.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Optional


def workspace_root_for_worker(wd: str | Path) -> Path:
    """Return the run workspace root for a worker cwd.

    Normal web runs use ``workspace/workers/<worker-id>``.  Unit tests and older
    callers may pass an arbitrary cwd; in that case the cwd's parent becomes a
    lightweight workspace root so local execution still uses the CAS protocol.

    F36: walk UP to the nearest `workers` ancestor — a worker that created
    NESTED subdirectories (workers/a/b/c) used to resolve to workers/a as the
    "root" and seed the CAS layout into the worker's own subtree."""
    p = Path(wd).resolve()
    while p.parent != p:
        if p.name == "workers":
            return p.parent
        p = p.parent
    return Path(wd).resolve().parent


def ensure_workspace(root: str | Path, *, runtime: dict[str, Any] | None = None) -> Path:
    root = Path(root)
    for rel in (
        "inputs/by-name",
        "inputs/objects",
        "shared/objects",
        "shared/links",
        "graph",
        "workers",
        "homes",
        "tmp",
        "logs",
        "final",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    index = root / "shared" / "index.jsonl"
    index.touch(exist_ok=True)
    write_manifest(root, runtime=runtime)
    return root


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_dir(path: Path) -> str:
    h = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = item.relative_to(path).as_posix().encode()
        h.update(rel + b"\0")
        with item.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def sha256_path(path: str | Path) -> str:
    p = Path(path)
    return _sha256_dir(p) if p.is_dir() else _sha256_file(p)


def object_path(root: str | Path, area: str, sha256: str) -> Path:
    if area not in {"inputs", "shared"}:
        raise ValueError(f"unknown CAS area: {area}")
    return Path(root) / area / "objects" / sha256[:2] / sha256[2:4] / sha256


def _atomic_materialize(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_parent = dst.parent
    tmp = tmp_parent / f".{dst.name}.staging.{os.getpid()}.{time.time_ns()}"
    try:
        if src.is_dir():
            shutil.copytree(src, tmp)
        else:
            try:
                os.link(src, tmp)
            except OSError:
                shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    except FileExistsError:
        pass
    finally:
        if tmp.exists():
            if tmp.is_dir():
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                try:
                    tmp.unlink()
                except OSError:
                    pass


def _replace_symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.unlink()
    except FileNotFoundError:
        pass
    link.symlink_to(target)


def relative_symlink(link: str | Path, target: str | Path) -> None:
    link = Path(link)
    target = Path(target)
    rel = os.path.relpath(target, start=link.parent)
    _replace_symlink(link, Path(rel))


def is_clean_name(name: str) -> bool:
    """F35: a clean name must be a single safe path segment. `..` / `.` / empty
    / separators were silently accepted (Path(name).name leaves `..` intact) and
    let a hostile attachment name escape the CAS layout (link created in the
    worker dir's PARENT, or symlink onto the inputs dir itself).

    Public so the PoC inheritance CONSUMER side (CliSolver._link_inherited_pocs)
    and the shared_graph WRITE side (save_poc) enforce the same rule — the pocs
    table is worker-writable, so a value that is fine at write time must still be
    re-validated before it is spliced into a filesystem path."""
    n = str(name or "")
    return bool(n) and n not in (".", "..") and "/" not in n and "\\" not in n and "\x00" not in n


def is_safe_relative_path(rel: str) -> bool:
    """A relative, non-escaping path string: no `..` segment, no absolute /
    drive-qualified path, no NUL. Worker-written `path` columns (PoC rows,
    shared artifacts) must pass this at the WRITE side; the consumer re-checks
    with resolve_inside before splicing into a real filesystem path."""
    r = str(rel or "")
    if not r or "\x00" in r:
        return False
    p = Path(r)
    # Windows quirk: `Path("/etc/passwd").is_absolute()` is False there (no
    # drive), yet `root / "/etc/passwd"` still resolves to `<drive>:/etc/passwd`
    # — OUTSIDE root. A leading separator must be rejected on every platform.
    if r.startswith("/") or r.startswith("\\"):
        return False
    if p.is_absolute() or p.drive:
        return False
    return ".." not in p.parts


def resolve_inside(root: str | Path, rel: str) -> Optional[Path]:
    """Resolve `root / rel` and return the resolved path ONLY if it stays inside
    `root`. Returns None for empty / absolute / drive-qualified / `..`-escaping
    relative paths.

    Third-round audit: the PoC inheritance consumer links `root / path` from
    worker-written rows — a path like `../../../etc/passwd` would escape the
    workspace root and create a symlink pointing OUTSIDE the CAS. Every caller
    must route worker-controlled relative paths through this before linking."""
    root_r = Path(root).resolve()
    rel = str(rel or "")
    if not rel:
        return None
    p = Path(rel)
    # Windows quirk: leading separator without drive is not is_absolute() there,
    # but `root / "/etc/passwd"` escapes to `<drive>:/etc/passwd` anyway.
    if rel.startswith("/") or rel.startswith("\\"):
        return None
    if p.is_absolute() or p.drive:  # drive-qualified (C:foo) is absolute-ish on Windows
        return None
    cand = (root_r / p).resolve()
    try:
        cand.relative_to(root_r)
    except ValueError:
        return None
    return cand


def materialize_input(root: str | Path, src: str | Path, *, name: str | None = None) -> dict[str, Any]:
    root = ensure_workspace(root)
    srcp = Path(src).resolve()
    if not srcp.exists():
        raise FileNotFoundError(srcp)
    digest = sha256_path(srcp)
    obj = object_path(root, "inputs", digest)
    _atomic_materialize(srcp, obj)
    # F35: validate the RAW name BEFORE Path().name — on Windows `Path("a\\b").name`
    # is "b", which would smuggle a separator past the check and still place the
    # link oddly.
    raw_name = name if name is not None else srcp.name
    if not is_clean_name(str(raw_name)):
        raise ValueError(f"unsafe attachment name: {raw_name!r}")
    clean_name = Path(str(raw_name)).name
    by_name = root / "inputs" / "by-name" / clean_name
    relative_symlink(by_name, obj)
    write_manifest(root)
    return {
        "name": clean_name,
        "sha256": digest,
        "object": obj,
        "by_name": by_name,
        "kind": "directory" if srcp.is_dir() else "file",
    }


def materialize_shared_artifact(
    root: str | Path,
    src: str | Path,
    *,
    name: str | None = None,
    kind: str = "derived",
    status: str = "available",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = ensure_workspace(root)
    srcp = Path(src).resolve()
    if not srcp.exists():
        raise FileNotFoundError(srcp)
    digest = sha256_path(srcp)
    obj = object_path(root, "shared", digest)
    _atomic_materialize(srcp, obj)
    # F35: raw-name validation BEFORE Path().name (see materialize_input).
    raw_name = name if name is not None else srcp.name
    if not is_clean_name(str(raw_name)):
        raise ValueError(f"unsafe artifact name: {raw_name!r}")
    clean_name = Path(str(raw_name)).name
    link = root / "shared" / "links" / clean_name
    relative_symlink(link, obj)
    row = {
        "ts": time.time(),
        "kind": kind,
        "status": status,
        "name": clean_name,
        "sha256": digest,
        "path": obj.relative_to(root).as_posix(),
        **(metadata or {}),
    }
    # index.jsonl is a rebuildable materialized view; callers should treat
    # shared_graph events as truth once artifact events exist.
    with (root / "shared" / "index.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    write_manifest(root)
    return {**row, "object": obj, "link": link}


def link_input_into_worker(root: str | Path, wd: str | Path, name: str) -> Path:
    root = ensure_workspace(root)
    # F35: raw-name validation BEFORE Path().name (see materialize_input).
    if not is_clean_name(str(name)):
        raise ValueError(f"unsafe link name: {name!r}")
    n = Path(str(name)).name
    dst = Path(wd) / n
    src = root / "inputs" / "by-name" / n
    relative_symlink(dst, src)
    return dst


def link_shared_into_worker(root: str | Path, wd: str | Path, name: str, sha256: str) -> Path:
    root = ensure_workspace(root)
    if not is_clean_name(str(name)):
        raise ValueError(f"unsafe link name: {name!r}")
    n = Path(str(name)).name
    dst = Path(wd) / "shared" / n
    src = object_path(root, "shared", sha256)
    # F37: a bad sha creates a dangling link silently — fail loudly instead.
    if not src.exists():
        raise FileNotFoundError(f"shared object missing: {src}")
    relative_symlink(dst, src)
    return dst


def write_manifest(root: str | Path, *, runtime: dict[str, Any] | None = None) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    inputs: list[dict[str, Any]] = []
    by_name = root / "inputs" / "by-name"
    if by_name.exists():
        for link in sorted(by_name.iterdir(), key=lambda p: p.name):
            try:
                resolved = link.resolve()
                sha = resolved.name
            except OSError:
                sha = ""
            inputs.append({
                "name": link.name,
                "sha256": sha,
                "path": link.relative_to(root).as_posix(),
                "object": f"inputs/objects/{sha[:2]}/{sha[2:4]}/{sha}" if sha else "",
            })
    manifest = {
        "version": 1,
        "topology": {
            "inputs": "inputs",
            "shared": "shared",
            "graph": "graph",
            "workers": "workers",
            "homes": "homes",
            "tmp": "tmp",
            "logs": "logs",
            "final": "final",
        },
        "inputs": inputs,
        "runtime": runtime or {},
        "artifact_truth": "shared_graph.events",
        "shared_index": "shared/index.jsonl (rebuildable materialized view)",
    }
    path = root / "manifest.json"
    fd, tmp_name = tempfile.mkstemp(prefix=".manifest.", suffix=".json", dir=str(root))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return path


def cleanup_worker_scratch(worker_root: str | Path, *, keep: Iterable[str] = ()) -> list[Path]:
    """Remove finished/failed worker scratch directories under ``workers/``.

    Callers can keep winner/current worker ids.  The function never touches
    sibling workspace directories such as shared, graph, final, or CAS objects.
    """
    root = Path(worker_root)
    keep_set = set(keep)
    removed: list[Path] = []
    if not root.exists():
        return removed
    for child in root.iterdir():
        if child.name.startswith("_") or child.name in keep_set:
            continue
        if child.is_symlink():
            # F38: a symlink pointing AT a directory used to pass is_dir() and
            # rmtree it (OSError swallowed by ignore_errors) — the dangling link
            # lingered. unlink the link itself.
            child.unlink(missing_ok=True)
            removed.append(child)
        elif child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child)
    return removed
