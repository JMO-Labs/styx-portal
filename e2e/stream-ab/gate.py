"""D47 gate: per-session results -> pass/fail verdict, JSON + markdown report. Pure Python."""
import json
from pathlib import Path

from latstats import pct

# D47: launch p95 < 10 s, stream RTT p95 < 80 ms, zero drops.
DEFAULTS = {"launch_p95_s": 10.0, "rtt_p95_ms": 80.0, "drops": 0}


def evaluate(rows: list, thresholds: dict | None = None) -> dict:
    """rows: {"session", "launch_s": float|None, "rtt_ms": [float], "drops": int}.
    A launch_s of None is a failed launch and fails the launch metric."""
    th = DEFAULTS | (thresholds or {})
    launches = [r["launch_s"] for r in rows if r.get("launch_s") is not None]
    failed = len(rows) - len(launches)
    rtt = [x for r in rows for x in r.get("rtt_ms") or []]
    drops = sum(r.get("drops") or 0 for r in rows)
    launch_p95, rtt_p95 = pct(launches, 95), pct(rtt, 95)
    metrics = {
        "launch_p95_s": {"value": launch_p95, "threshold": th["launch_p95_s"], "failed_launches": failed,
                         "pass": launch_p95 is not None and failed == 0 and launch_p95 < th["launch_p95_s"]},
        "rtt_p95_ms": {"value": rtt_p95, "threshold": th["rtt_p95_ms"],
                       "pass": rtt_p95 is not None and rtt_p95 < th["rtt_p95_ms"]},
        "drops": {"value": drops, "threshold": th["drops"], "pass": bool(rows) and drops <= th["drops"]},
    }
    ok = bool(rows) and all(m["pass"] for m in metrics.values())
    return {"verdict": "pass" if ok else "fail", "n_sessions": len(rows), "metrics": metrics}


def _v(x) -> str:
    return "-" if x is None else f"{x:.1f}" if isinstance(x, float) else str(x)


def markdown(result: dict) -> str:
    out = [f"# D47 gate: {result['verdict'].upper()} ({result['n_sessions']} sessions)", "",
           "| metric | value | threshold | result |", "|---|---|---|---|"]
    for name, m in result["metrics"].items():
        out.append(f"| {name} | {_v(m['value'])} | {_v(m['threshold'])} | {'PASS' if m['pass'] else 'FAIL'} |")
    return "\n".join(out) + "\n"


def write_report(result: dict, path_stem) -> None:
    stem = Path(path_stem)
    stem.with_name(stem.name + ".json").write_text(json.dumps(result, indent=2) + "\n")
    stem.with_name(stem.name + ".md").write_text(markdown(result))
