"""RTO/RPO rules and the versioned evidence report (JSON + Markdown)."""

import hashlib
import json
from pathlib import Path

from .checks import parse_ts

SCHEMA_VERSION = "1.0"
RTO_MAX_S = 8 * 3600
RPO_MAX_S = 24 * 3600
CONTROLS = ["CP-4", "CP-9", "CP-10", "R03"]


def _within(start, end, limit):
    if start is None or end is None:
        return None, False
    s = int((end - start).total_seconds())
    return s, s <= limit


def rto(t0, t_end):
    """(seconds, pass): T0 to the last passing health check, pass if <= 8 h."""
    return _within(t0, t_end, RTO_MAX_S)


def rpo(incident, point):
    """(seconds, pass): incident time minus the newest recovered point, pass if <= 24 h."""
    return _within(point, incident, RPO_MAX_S)


def load_steps(rd):
    """steps.jsonl -> steps[]; manual `mark` start/end events are merged into one step."""
    p = Path(rd) / "steps.jsonl"
    events = [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []
    steps, open_ = [], {}
    for e in events:
        if "event" not in e:
            steps.append(e)
            continue
        s = open_.pop(e["id"], None) if e["event"] == "end" else None
        if s is None:
            s = {"id": e["id"], "start": None, "end": None, "actor": e["actor"],
                 "command": "manual (runbook)", "result": "started"}
            steps.append(s)
        if e["event"] == "start":
            s["start"] = e["time"]
            open_[e["id"]] = s
        else:
            s.update(end=e["time"], actor=e["actor"], result="done")
    return steps


def t0(cfg, state, steps):
    """full-site: start of the manual T0 step. data-only: harness start."""
    if cfg["mode"] == "full-site":
        marks = [s for s in steps if s["id"] == "T0" and s.get("start")]
        return parse_ts(marks[0]["start"]) if marks else None
    return parse_ts(state.get("started"))


def build(cfg, rd):
    rd = Path(rd)
    sp = rd / "state.json"
    state = json.loads(sp.read_text()) if sp.exists() else {}
    steps = load_steps(rd)
    log = rd / "steps.jsonl"
    start = t0(cfg, state, steps)
    rto_s, rto_ok = rto(start, parse_ts(state.get("t_end")))
    incident = parse_ts(cfg.get("incident_time") or state.get("started"))
    datasets, ok = [], rto_ok and bool(state.get("datasets"))
    for d in state.get("datasets", []):
        rpo_s, rpo_ok = (None, True) if d["source"] == "app" else \
            rpo(incident, parse_ts(d["recovered_point"]))
        ok = ok and rpo_ok and all(c["pass"] for c in d["checks"])
        datasets.append({**d, "rpo_seconds": rpo_s})
    return {
        "schema_version": SCHEMA_VERSION, "run_id": cfg["run_id"], "mode": cfg["mode"],
        "target": {"cluster_uid": state.get("cluster_uid"), "namespace": cfg["namespace"]},
        "operator": cfg.get("operator"), "witness": cfg.get("witness"),
        "git_sha": state.get("git_sha", "unknown"),
        "tool_versions": state.get("tool_versions", {}),
        "rto_clock_start": cfg.get("rto_clock_start"),
        "t0": start.isoformat().replace("+00:00", "Z") if start else None,
        "t_end": state.get("t_end"),
        "incident_time": incident.isoformat().replace("+00:00", "Z") if incident else None,
        "rto_seconds": rto_s, "rto_limit_seconds": RTO_MAX_S, "rpo_limit_seconds": RPO_MAX_S,
        "steps": steps, "datasets": datasets, "pass": ok, "controls": CONTROLS,
        "log_sha256": hashlib.sha256(log.read_bytes() if log.exists() else b"").hexdigest(),
    }


def _hms(s):
    return "n/a" if s is None else f"{s // 3600}h {s % 3600 // 60:02d}m {s % 60:02d}s"


def _cell(v):
    return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")


def markdown(rep):
    verdict = "PASS" if rep["pass"] else "FAIL"
    lines = [
        f"# DR restore test {rep['run_id']}: {verdict}", "",
        f"- Mode: {rep['mode']}; controls: {', '.join(rep['controls'])}",
        f"- Target: cluster `{rep['target']['cluster_uid']}`, namespace "
        f"`{rep['target']['namespace']}`",
        f"- Operator: {rep['operator']}; witness: {rep['witness']}",
        f"- Harness git SHA: `{rep['git_sha']}`; step log sha256: `{rep['log_sha256']}`",
        f"- RTO: {_hms(rep['rto_seconds'])} (limit 8 h; clock starts at: "
        f"{rep['rto_clock_start']}; T0 {rep['t0']}, end {rep['t_end']})",
        f"- Incident time for RPO: {rep['incident_time']} (limit 24 h)", "",
        "## Data sets", "", "| Source | Backup | Recovered point | RPO | Check | Result | Detail |",
        "|---|---|---|---|---|---|---|"]
    for d in rep["datasets"]:
        for c in d["checks"]:
            lines.append("| " + " | ".join(_cell(x) for x in (
                d["source"], d["backup_id"], d["recovered_point"], _hms(d["rpo_seconds"]),
                c["name"], "pass" if c["pass"] else "FAIL", c["detail"])) + " |")
    lines += ["", "## Steps", "", "| Step | Start | End | Actor | Command | Result |",
              "|---|---|---|---|---|---|"]
    for s in rep["steps"]:
        lines.append("| " + " | ".join(_cell(s.get(k)) for k in (
            "id", "start", "end", "actor", "command", "result")) + " |")
    lines += ["", "## Sign-off", "", "- Operator: ____________ date: ______",
              "- Witness: ____________ date: ______", "- ISSO: ____________ date: ______", ""]
    return "\n".join(lines)
