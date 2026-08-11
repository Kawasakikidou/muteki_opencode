"""CTF 比赛模式(batch runner)测试:manifest 解析 / Challenge 构造 / 战报生成。

纯单元测试,不真正调 Swarm(避免烧 token)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from muteki.batch.ctf_runner import (
    BatchConfig, _challenge_from_spec, load_manifest, write_report,
)


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
