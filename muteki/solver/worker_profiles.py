"""WorkerProfile normalization shared by the web config and swarm scheduler.

Profiles are the scheduling unit.  ``profile["name"]`` is what the coordinator
selects; ``profile["engine"]`` is the concrete CLI transport family.
"""

from __future__ import annotations

from typing import Any


# worker profile 可指向的基础引擎。opencode 作为第 4 引擎加入
# (muteki-for-ctf):其 CLI 通过 `opencode run --format json` 外部驱动。
VALID_BASE_ENGINES = ("claude", "codex", "cursor", "opencode")
TRANSPORT_TO_ENGINE = {
    "claude": "claude",
    "claude_code": "claude",
    "codex": "codex",
    "codex_cli": "codex",
    "cursor": "cursor",
    "cursor_agent": "cursor",
    "opencode": "opencode",
    "opencode_cli": "opencode",
}
DEFAULT_ROLES = ["race", "bootstrap", "explore", "respond", "review"]


def coerce_nonneg_int(value: Any, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n >= 0 else default


def coerce_pos_int(value: Any, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


def base_engine_for_profile(profile_or_name: Any) -> str:
    """Resolve a profile dict OR a bare string to a BASE engine (claude/codex/cursor).

    A bare string may be a base engine ("codex"), a transport ("codex_cli"), or a
    PROFILE ID ("codex-sub-container"). Profile ids are "<base>-<suffix>", so when a
    string is neither a known base nor transport we recover the base from its segments
    (the first segment that is a valid base engine). This is what keeps a profile id
    from being passed straight to DRIVERS[...] (→ KeyError) downstream. The original
    string is returned only when nothing resolves, so callers can still error clearly.
    """
    if isinstance(profile_or_name, dict):
        transport = str(profile_or_name.get("transport") or "").strip()
        engine = str(profile_or_name.get("engine") or "").strip()
        return TRANSPORT_TO_ENGINE.get(transport, engine)
    s = str(profile_or_name or "").strip()
    if s in TRANSPORT_TO_ENGINE:
        return TRANSPORT_TO_ENGINE[s]
    if s in VALID_BASE_ENGINES:
        return s
    # F40: profile id like "codex-sub-container" / "cursor-api-container" →
    # recover base — but ONLY from the FIRST segment. "sub-codex" / "my-claude-
    # runner" used to resolve an engine out of the MIDDLE of an arbitrary string,
    # silently masking typos and misconfigurations.
    first = s.split("-", 1)[0]
    if first in VALID_BASE_ENGINES:
        return first
    if first in TRANSPORT_TO_ENGINE:
        return TRANSPORT_TO_ENGINE[first]
    return s


def normalize_worker_profile(item: dict[str, Any], *, reject_invalid: bool = False) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        if reject_invalid:
            raise ValueError("worker profile must be an object")
        return None
    if not item.get("enabled", True):
        return None
    transport = str(item.get("transport") or item.get("engine") or "").strip()
    engine = TRANSPORT_TO_ENGINE.get(transport, str(item.get("engine") or "").strip())
    if engine not in VALID_BASE_ENGINES:
        if reject_invalid:
            raise ValueError("worker profile requires valid transport/engine")
        return None
    pid = str(item.get("name") or item.get("id") or "").strip()
    if not pid:
        if reject_invalid:
            raise ValueError("worker profile requires name or id")
        return None
    raw_roles = item.get("roles")
    roles = [
        str(r).strip()
        for r in raw_roles
        if isinstance(r, str) and str(r).strip()
    ] if isinstance(raw_roles, list) else []
    if not roles:
        roles = list(DEFAULT_ROLES)
    elif "review" not in roles and any(
        r in roles for r in ("race", "bootstrap", "explore", "respond")
    ):
        # Compatibility migration for profiles saved before the review-arbiter
        # role existed: execution-capable profiles should be selectable as the
        # single core review worker unless the operator made a non-execution-only
        # profile on purpose.
        roles = [*roles, "review"]
    credential_mode = str(
        item.get("credential_mode") or item.get("auth") or "subscription"
    ).strip() or "subscription"
    if "credential_account" in item:
        raw_account = item.get("credential_account")
    elif "credential_account_ref" in item:
        raw_account = item.get("credential_account_ref")
    else:
        raw_account = f"{engine}-main"
    # NOTE: an explicit EMPTY credential_account is INTENTIONAL — local +
    # subscription mode means "inherit the host CLI login", and
    # test_config_preserves_blank_credential_account_for_local_subscription_cli
    # pins that. Do NOT substitute the {engine}-main default here (an earlier
    # "fix" for that broke the contract).
    credential_account = str(raw_account or "").strip()
    normalized = {
        "id": pid,
        "name": pid,
        # human-readable display name, carried through so a seat-id-based pid (post
        # identity migration) still renders a friendly name in the UI. Defaults to
        # the pid when no explicit label is given.
        "label": str(item.get("label") or pid).strip(),
        "engine": engine,
        "transport": transport or engine,
        "credential_mode": credential_mode,
        "auth": credential_mode,
        "credential_account": credential_account,
        "api_key_ref": str(item.get("api_key_ref") or "").strip(),
        "base_url": str(item.get("base_url") or "").strip(),
        "wire_api": str(item.get("wire_api") or ("responses" if engine == "codex" else "")).strip(),
        "runtime": str(item.get("runtime") or "docker-web").strip(),
        "roles": roles,
        # F39: web config / env injection often hands booleans as STRINGS —
        # bool("false") is True, which silently put a "race": "false" profile
        # into the race roster. Coerce like the other fields.
        "race": _coerce_bool(item.get("race", "race" in roles)),
        "max_running": coerce_pos_int(item.get("max_running"), 1),
        # 0 means "inherit the global review.max_concurrent"; review capacity is
        # intentionally separate from max_running, which now only gates ordinary
        # race/bootstrap/explore/respond workers.
        "max_review_running": coerce_nonneg_int(item.get("max_review_running"), 0),
        "priority": coerce_nonneg_int(item.get("priority"), 100),
        "model": str(item.get("model") or "").strip(),
        "enabled": True,
    }
    return normalized


def _coerce_bool(v: Any) -> bool:
    """F39: string-safe bool coercion — 'false'/'0'/'no'/'off' are False;
    non-string values use plain bool()."""
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return bool(v)


def normalize_worker_profiles(value: Any, *, defaults: list[dict[str, Any]] | None = None,
                              reject_invalid: bool = False) -> list[dict[str, Any]]:
    if value is None:
        return [dict(p) for p in (defaults or [])]
    if not isinstance(value, list):
        if reject_invalid:
            raise ValueError("worker_profiles must be a list")
        return [dict(p) for p in (defaults or [])]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        profile = normalize_worker_profile(item, reject_invalid=reject_invalid)
        if profile is None:
            continue
        if profile["name"] in seen:
            if reject_invalid:
                raise ValueError("worker profile names must be unique")
            continue
        seen.add(profile["name"])
        out.append(profile)
    if not value:
        # explicit EMPTY config → defaults (historical behavior)
        return [dict(p) for p in (defaults or [])]
    # F41: a NON-empty config that filtered down to nothing (all profiles
    # invalid / all disabled) must NOT silently fall back to defaults — the
    # operator explicitly configured something, often meaning "disable the
    # engines"; resurrecting the default roster would re-enable them behind
    # the operator's back.
    return out


def profile_names(profiles: list[dict[str, Any]]) -> list[str]:
    return [str(p["name"]) for p in profiles if p.get("enabled", True)]


def normalize_profile_roster(values: Any, profiles: list[dict[str, Any]]) -> list[str]:
    """Map profile names and legacy base-engine names to profile-name roster.

    Unknown names are ignored. A legacy base engine expands to every matching
    profile in priority/name order.
    """

    if not isinstance(values, (list, tuple)):
        return []
    by_name = {str(p["name"]): p for p in profiles}
    by_engine: dict[str, list[str]] = {}
    # coerce_nonneg_int (NOT `priority or 100`): preserve a legal priority 0
    # (highest precedence) instead of silently demoting it to the default.
    for p in sorted(profiles, key=lambda p: (coerce_nonneg_int(p.get("priority"), 100), str(p["name"]))):
        by_engine.setdefault(str(p["engine"]), []).append(str(p["name"]))
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            continue
        names = [raw] if raw in by_name else by_engine.get(raw, [])
        for name in names:
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def profile_uses_endpoint(profile: dict[str, Any] | None) -> bool:
    if not profile:
        return False
    return bool(profile.get("base_url"))


def resolve_seat_ref(
    ref: Any,
    *,
    seats: list[dict[str, Any]],
    alias_table: dict[str, str] | None = None,
) -> str | None:
    """THE single seat-reference resolver (plan §5.0(b)).

    A foreign key in config (engines[]/review.engine/race_engines/...) may name a
    seat THREE ways:
      - a new seat id (`seat_claude_ab12cd`),
      - a legacy profile name (`claude-local`),
      - a legacy hyphen "canonical" alias (`claude-api-local`, from the old
        worker_config._canonical_profile_id), OR a bare base engine (`claude`).
    All four must resolve to the new seat id. Shared by worker_config / drivers /
    server / swarm so they can never disagree.

    Returns the matched seat id; None when nothing matches (caller decides the
    fallback — NEVER silently swallowed) or when a bare engine is ambiguous across
    multiple seats (None + the caller can expand via the engine fan-out instead).
    """
    if not isinstance(ref, str) or not ref.strip():
        return None
    ref = ref.strip()
    by_id = {str(s.get("id")): s for s in seats if isinstance(s, dict) and s.get("id")}
    if ref in by_id:
        return ref
    alias_table = alias_table or {}
    if ref in alias_table and alias_table[ref] in by_id:
        return alias_table[ref]
    # label match (legacy name kept as the seat label).
    by_label = {str(s.get("label")): str(s.get("id")) for s in seats
                if isinstance(s, dict) and s.get("label")}
    if ref in by_label:
        return by_label[ref]
    # bare base engine → resolve ONLY if exactly one seat for that engine (else
    # ambiguous: the caller should fan out across the engine's seats instead).
    if ref in VALID_BASE_ENGINES:
        matches = [str(s["id"]) for s in seats
                   if isinstance(s, dict) and str(s.get("engine")) == ref and s.get("id")]
        return matches[0] if len(matches) == 1 else None
    return None
