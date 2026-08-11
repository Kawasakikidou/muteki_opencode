"""CTF 比赛模式批量运行器(muteki-for-ctf)。

把一批题目(manifest JSON)顺序/并行跑完,汇总成战报(Markdown + JSON)。
每题默认走"快解模式"(单引擎 + 短预算),可逐题覆盖。

典型用法:
    uv run python -m muteki.batch.ctf_runner manifest.json \
        --report out/battle_report.md --workers 1
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from muteki.models.solve_graph import Challenge
from muteki.sandbox.manager import SandboxManager
from muteki.solver.types import SolverConfig
from muteki.swarm.swarm import Swarm
from muteki.core.event_bus import EventBus


# ── 战报结果结构 ─────────────────────────────────────────────────────────────

@dataclass
class ChallengeResult:
    """一道题的一次运行结果(用于战报汇总)。"""
    id: str
    name: str
    category: str = ""
    solved: bool = False
    flag: str = ""
    elapsed_s: float = 0.0
    error: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "category": self.category,
            "solved": self.solved, "flag": self.flag,
            "elapsed_s": round(self.elapsed_s, 1), "error": self.error,
        }


# ── 单题运行 ─────────────────────────────────────────────────────────────────

def _challenge_from_spec(spec: dict[str, Any], work_root: Path) -> Challenge:
    """从 manifest 条目构造 Challenge;附件复制进工作目录并重写路径。"""
    cid = str(spec.get("id") or spec.get("name") or "challenge").strip()
    attachments: list[str] = []
    for raw in (spec.get("attachments") or []):
        src = Path(raw)
        if not src.exists():
            continue
        dest = work_root / "inputs" / f"{cid}" / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            shutil.copy2(src, dest)
            attachments.append(str(dest))
    return Challenge(
        id=cid,
        name=str(spec.get("name") or cid),
        category=str(spec.get("category") or "misc"),
        points=int(spec.get("points") or 0),
        description=str(spec.get("description") or ""),
        attachments=attachments,
        target=str(spec.get("target") or "") or None,
        flag_format=str(spec.get("flag_format") or r"flag\{.*?\}"),
        flag_format_hint=str(spec.get("flag_format_hint") or ""),
        multi_flag=bool(spec.get("multi_flag", False)),
        expected_flags=int(spec.get("expected_flags") or 1),
    )


async def _run_one(spec: dict[str, Any], cfg: "BatchConfig", work_root: Path,
                   run_idx: int, total: int) -> ChallengeResult:
    """跑一道题(fast 模式默认),返回结果。"""
    res = ChallengeResult(
        id=str(spec.get("id") or spec.get("name") or "challenge").strip(),
        name=str(spec.get("name") or spec.get("id") or "challenge").strip(),
        category=str(spec.get("category") or ""),
    )
    t0 = time.monotonic()
    print(f"[{run_idx}/{total}] {res.name} ({res.category}) 开始…", flush=True)
    try:
        ch = _challenge_from_spec(spec, work_root)
        run_id = f"batch-{res.id}"
        sandbox = SandboxManager(root=work_root / "sbx" / res.id)
        graph_dir = work_root / "graph" / res.id
        worker_root = work_root / "workers" / res.id
        # 批量模式默认单引擎(fast):短预算 + 无协调器,逐题串行。
        engines = list(cfg.engines or [])
        # 蒸馏飞轮(§16):成功解 → 可复用模板,后续相似题自动注入先验。
        # knowledge 目录可用 MUTEKI_KNOWLEDGE_DIR 覆盖。
        from muteki.learning.distill import TemplateStore
        knowledge = TemplateStore(
            root=os.environ.get("MUTEKI_KNOWLEDGE_DIR", "knowledge"))
        swarm = Swarm(
            ch, [], llm=None, sandbox=sandbox,
            bus=EventBus(),
            config=SolverConfig(), run_id=run_id,
            graph_dir=graph_dir, worker_root=worker_root,
            knowledge=knowledge,
            engines=engines, cli_race=True, cli_engine=engines[0] if engines else "opencode",
            start_workers=1, max_workers=1,
            coordinator=False, race_scout=True,
            race_engines=None, race_timeout=min(cfg.timeout, 720),
            wall_clock_budget=float(cfg.timeout),
            cold_start=True,
            worker_backend=cfg.backend,
            credential_accounts_root=cfg.accounts_root,
        )
        outcome = await swarm.run()
        res.solved = bool(outcome.solved)
        flags = getattr(outcome, "flags", None) or []
        if flags:
            res.flag = str(flags[0])
        if getattr(outcome, "error", None):
            res.error = str(outcome.error)[:500]
    except Exception as exc:  # noqa: BLE001 — 单题失败不拖垮整个比赛
        res.error = f"{type(exc).__name__}: {exc}"[:500]
    res.elapsed_s = time.monotonic() - t0
    status = "✅ 解出" if res.solved else "❌ 未解"
    print(f"[{run_idx}/{total}] {res.name}: {status} "
          f"{res.flag or ''} ({res.elapsed_s:.0f}s) {res.error}", flush=True)
    return res


# ── 配置与汇总 ───────────────────────────────────────────────────────────────

@dataclass
class BatchConfig:
    engines: list[str] = field(default_factory=lambda: ["opencode"])
    model: str = ""             # 空 = opencode 全局默认(见 ~/.config/opencode/opencode.jsonc)
    timeout: int = 300          # 每题墙钟预算(秒)
    backend: str = "local"      # local | container
    accounts_root: Optional[str] = None


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("challenges"), list):
        raise ValueError("manifest must be {\"challenges\": [...]}")
    return data


def write_report(results: list[ChallengeResult], cfg: BatchConfig,
                 out_md: Path, out_json: Optional[Path] = None) -> None:
    """汇总战报:Markdown(人读)+ JSON(机读)。"""
    solved = [r for r in results if r.solved]
    total = len(results)
    lines = [
        "# CTF 批量战报",
        "",
        f"- 总题数: **{total}**  ·  解出: **{len(solved)}**  ·  "
        f"未解: **{total - len(solved)}**  ·  总耗时: "
        f"**{sum(r.elapsed_s for r in results):.0f}s**",
        "",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"## {i}. {r.name} (`{r.id}`)")
        lines.append("")
        lines.append(f"- 类别: {r.category or '-'}  ·  状态: "
                     f"{'✅ 解出' if r.solved else '❌ 未解'}")
        lines.append(f"- 用时: {r.elapsed_s:.0f}s")
        if r.flag:
            lines.append(f"- Flag: `{r.flag}`")
        if r.error:
            lines.append(f"- 错误: {r.error}")
        lines.append("")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")
    if out_json is not None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(
            json.dumps({"solved": len(solved), "total": total,
                        "results": [r.to_dict() for r in results]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")


# ── 入口 ─────────────────────────────────────────────────────────────────────

async def _main(manifest_path: str, report_path: str, workers: int) -> int:
    manifest = load_manifest(Path(manifest_path))
    cfg = BatchConfig(
        engines=[str(e) for e in manifest.get("engines") or ["opencode"]],
        model=str(manifest.get("model") or "").strip(),
        timeout=int(manifest.get("timeout") or 300),
        backend=str(manifest.get("backend") or "local"),
        accounts_root=os.environ.get("MUTEKI_ACCOUNTS_ROOT"),
    )
    if cfg.model:
        # manifest 指定模型 → 注入 MUTEKI_WORKER_MODEL(worker 透传 --model)。
        # 更换模型接口:改 manifest 的 model 字段即可(如 deepseek/deepseek-v4-pro)。
        os.environ["MUTEKI_WORKER_MODEL"] = cfg.model
    out_dir = Path(report_path).parent
    work_root = out_dir / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    specs = manifest["challenges"]
    results: list[ChallengeResult] = []
    # 串行逐题(workers=1 默认;并行留给后续迭代,避免同时打靶互相干扰)
    for idx, spec in enumerate(specs, 1):
        results.append(await _run_one(spec, cfg, work_root, idx, len(specs)))
    write_report(results, cfg, Path(report_path),
                 out_json=out_dir / "battle_report.json")
    print(f"\n战报已生成: {report_path}")
    return 0 if all(r.solved for r in results) else 1


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="muteki CTF 比赛模式批量运行器")
    ap.add_argument("manifest", help="题目清单 JSON(见 muteki/batch/README)")
    ap.add_argument("--report", default="battle_report.md", help="战报输出路径")
    ap.add_argument("--workers", type=int, default=1, help="并行度(当前仅 1)")
    args = ap.parse_args()
    try:
        return asyncio.run(_main(args.manifest, args.report, args.workers))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
