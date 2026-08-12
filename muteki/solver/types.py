"""Shared solver value types (config + outcome).

Extracted from the (now-removed) code-driven solver so the CLI executor and the
swarm can depend on these dataclasses without importing the old Solver class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from muteki.models.solve_graph import SolveGraph


@dataclass
class SolverConfig:
    """Vestigial config object — kept only as a call-site placeholder.

    The code-driven solver that consumed these fields is gone; the CLI executor
    and swarm take their knobs (timeouts, budgets, engine roster, …) directly
    via constructor args. All fields that were zero-reference in production
    (code_timeout/temperature/max_tokens/stdout_limit/reason_*) were deleted
    (run-fix); this empty shell stays so existing `config=SolverConfig()`
    call sites keep compiling. Do not add new knobs here — add them to Swarm /
    CliSolver constructors.
    """
    pass


@dataclass
class SolveOutcome:
    solved: bool
    flag: Optional[str]
    steps: int
    graph: SolveGraph
    reason: str = ""
    # multi-flag: every distinct flag this worker accepted this run (dedup, in
    # discovery order). `flag` stays as the FIRST one for back-compat reads.
    # Single-flag challenges have len(flags) <= 1, so `flag` and `flags[0]` agree.
    flags: list[str] = field(default_factory=list)
    # CLI continuation handle (CliSolver only): the winning worker's shelled-CLI
    # session id + engine + cwd, so a post-solve standby driver can resume the
    # SAME session (`claude -r <session>`) to answer a human follow-up, mark a
    # false-positive and keep solving, or write a writeup — with the worker's full
    # memory intact. None for non-CLI paths or when no session was assigned.
    session: Optional[str] = None
    engine: str = ""
    workdir: str = ""
    # respond mode (standby) only: the worker's conversational reply / writeup body,
    # so the standby driver can persist it (e.g. writeup.md) without re-parsing the
    # event stream. Empty for solve runs.
    reply: str = ""
