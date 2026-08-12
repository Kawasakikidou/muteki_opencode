"""CTF 比赛模式(batch runner)测试:manifest 解析 / Challenge 构造 / 战报生成。

纯单元测试,不真正调 Swarm(避免烧 token)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from muteki.batch.ctf_runner import (
    BatchConfig, _challenge_from_spec, config_from_manifest, load_manifest,
    write_report,
)


def test_config_from_manifest_parses_retry_and_coordinator_fields():
    cfg = config_from_manifest({
        "challenges": [{"id": "c1"}],
        "engines": ["opencode"],
        "timeout": 120,
        "retry": 2,
        "retry_budget_scale": 1.5,
        "coordinator": True,
        "start_workers": 2,
        "max_workers": 3,
    })
    assert cfg.retry == 2
    assert cfg.retry_budget_scale == 1.5
    assert cfg.coordinator is True
    assert cfg.start_workers == 2 and cfg.max_workers == 3
    assert cfg.timeout == 120
    # 缺省值保持快解默认(不意外开启 coordinator/重试)
    default = config_from_manifest({"challenges": []})
    assert default.retry == 0 and default.coordinator is False
    assert default.start_workers == 1 and default.max_workers == 1


def test_run_one_retries_with_relay_semantics(tmp_path, monkeypatch):
    """run-fix: 失败重试 = 接力 —— 同一 graph_dir + cold_start=(attempt==0),
    第二轮复用第一轮的 shared_graph.db(证据/dead-end/rejected flags 全保留),
    不是重头再来;墙钟预算按 retry_budget_scale 递增。"""
    import asyncio
    from types import SimpleNamespace

    from muteki.batch.ctf_runner import BatchConfig, _run_one

    monkeypatch.setenv("MUTEKI_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))

    calls: list[dict] = []
    fail_first: dict[str, bool] = {"on": True}

    class FakeSwarm:
        def __init__(self, *args, **kwargs):
            self._kwargs = kwargs
            calls.append(kwargs)

        async def run(self):
            # 发一个真实事件,让 SessionStore sink 真正落盘(验证 batch 的事件
            # 流持久化链路,而不只是"注册了 sink")
            bus = self._kwargs.get("bus")
            if bus is not None:
                from muteki.core.event_bus import Event
                from muteki.core.events import EventType
                await bus.emit(Event(
                    event_type=EventType.RUN_STARTED,
                    run_id=self._kwargs["run_id"],
                    ts=0.0, payload={"challenge": {"name": "x"}}))
            solved = not fail_first["on"] or len(calls) >= 2
            return SimpleNamespace(solved=solved, flags=[], error=None)

    monkeypatch.setattr("muteki.batch.ctf_runner.Swarm", FakeSwarm)

    spec = {"id": "c1", "name": "x", "category": "web"}
    cfg = BatchConfig(retry=1, timeout=60, retry_budget_scale=2.0)
    res = asyncio.run(_run_one(spec, cfg, tmp_path / "work", 1, 1))
    assert res.solved is True
    assert len(calls) == 2, "第一轮失败后必须接力第二轮"
    assert calls[0]["cold_start"] is True
    assert calls[1]["cold_start"] is False, "接力轮必须复用已有图"
    assert calls[0]["graph_dir"] == calls[1]["graph_dir"], "接力:同一张图"
    assert calls[0]["wall_clock_budget"] == 60
    assert calls[1]["wall_clock_budget"] == 120, "scale=2.0 → 第二轮预算翻倍"
    assert len(res.notes) + 1 == 2, "两轮尝试"
    assert res.events_path.endswith(".jsonl")
    # 事件流确实落盘了(bus 挂了 SessionStore sink)
    assert (tmp_path / "work" / "sessions" / "batch-c1.jsonl").exists()
    # 全部解出后不再额外重试
    calls.clear()
    fail_first["on"] = False
    res2 = asyncio.run(_run_one(spec, cfg, tmp_path / "work2", 1, 1))
    assert len(calls) == 1 and res2.solved is True


def test_load_manifest_rejects_bad_shape(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"challenges": "nope"}')
    with pytest.raises(ValueError):
        load_manifest(bad)
    missing = tmp_path / "ghost.json"
    with pytest.raises(FileNotFoundError):
        load_manifest(missing)


def test_challenge_from_spec_with_attachments(tmp_path):
    attach = tmp_path / "enc.txt"
    attach.write_text("ciphertext")
    spec = {
        "id": "c1", "name": "crypto1", "category": "crypto", "points": 100,
        "description": "solve", "flag_format": "SHCTF\\{[^}]+\\}",
        "target": "10.0.0.1:1337",
        "attachments": [str(attach), str(tmp_path / "ghost.bin")],  # 后者不存在 → 过滤
    }
    ch = _challenge_from_spec(spec, tmp_path / "work")
    assert ch.id == "c1" and ch.category == "crypto"
    assert ch.flag_format == "SHCTF\\{[^}]+\\}"
    assert ch.target == "10.0.0.1:1337"
    assert len(ch.attachments) == 1                      # 不存在的附件被过滤
    assert Path(ch.attachments[0]).exists()              # 附件已复制进 work 目录
    assert Path(ch.attachments[0]).read_text() == "ciphertext"


def test_write_report_markdown_and_json(tmp_path):
    from muteki.batch.ctf_runner import ChallengeResult
    results = [
        ChallengeResult(id="a", name="Alpha", category="misc", solved=True,
                        flag="flag{alpha}", elapsed_s=12.5),
        ChallengeResult(id="b", name="Beta", category="crypto", solved=False,
                        elapsed_s=300.0, error="timeout"),
    ]
    md = tmp_path / "r" / "report.md"
    js = tmp_path / "r" / "report.json"
    write_report(results, BatchConfig(), md, js)
    text = md.read_text(encoding="utf-8")
    assert "总题数: **2**" in text and "解出: **1**" in text
    assert "`flag{alpha}`" in text and "timeout" in text
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["solved"] == 1 and data["total"] == 2
    assert data["results"][0]["flag"] == "flag{alpha}"
