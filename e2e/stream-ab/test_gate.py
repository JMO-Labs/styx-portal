import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate as G  # noqa: E402


def row(s="a", launch=3.0, rtt=(20.0, 30.0), drops=0):
    return {"session": s, "launch_s": launch, "rtt_ms": list(rtt), "drops": drops}


def test_pass():
    r = G.evaluate([row("a"), row("b", launch=5.0)])
    assert r["verdict"] == "pass" and r["n_sessions"] == 2
    for m in ("launch_p95_s", "rtt_p95_ms", "drops"):
        assert r["metrics"][m]["pass"] is True
    assert r["metrics"]["drops"]["threshold"] == 0
    assert r["metrics"]["launch_p95_s"]["value"] == 4.9


def test_launch_slow_fails():
    r = G.evaluate([row(launch=10.0)])
    assert r["verdict"] == "fail" and not r["metrics"]["launch_p95_s"]["pass"]
    assert r["metrics"]["rtt_p95_ms"]["pass"]


def test_failed_launch_fails():
    r = G.evaluate([row("a"), row("b", launch=None)])
    assert r["verdict"] == "fail" and not r["metrics"]["launch_p95_s"]["pass"]
    assert r["metrics"]["launch_p95_s"]["failed_launches"] == 1


def test_rtt_fails():
    r = G.evaluate([row(rtt=[100.0] * 5)])
    assert r["verdict"] == "fail" and not r["metrics"]["rtt_p95_ms"]["pass"]


def test_drops_fail():
    r = G.evaluate([row(drops=1)])
    assert r["verdict"] == "fail" and r["metrics"]["drops"]["value"] == 1
    assert not r["metrics"]["drops"]["pass"]


def test_empty_fails():
    r = G.evaluate([])
    assert r["verdict"] == "fail" and r["n_sessions"] == 0


def test_custom_thresholds():
    r = G.evaluate([row(drops=2)], {"drops": 5})
    assert r["verdict"] == "pass"


def test_write_report(tmp_path):
    r = G.evaluate([row(drops=1)])
    stem = tmp_path / "rep"
    G.write_report(r, stem)
    assert json.loads(stem.with_suffix(".json").read_text())["verdict"] == "fail"
    md = stem.with_suffix(".md").read_text()
    assert "| metric | value | threshold | result |" in md
    assert "| drops | 1 | 0 | FAIL |" in md and "PASS" in md
