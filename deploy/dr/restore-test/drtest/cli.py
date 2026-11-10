"""styx_drtest CLI: plan | run | fingerprint | mark | report | teardown."""

import argparse
import json
import re
from pathlib import Path

from . import checks, run
from .guards import Refused

RUN_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
SECRET_KEY = re.compile(r"pass|secret|token|access_key|key_id|credential", re.I)
REQUIRED = ("run_id", "mode", "namespace", "prod_cluster_uids", "scratch_cluster_uids",
            "evidence_root", "alembic_head", "health_url")


def _secret_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if SECRET_KEY.search(k):
                yield f"{path}{k}"
            yield from _secret_keys(v, f"{path}{k}.")
    elif isinstance(obj, list):
        for v in obj:
            yield from _secret_keys(v, path)


def load_config(path):
    try:
        cfg = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise Refused(f"cannot read config {path}: {e}") from None
    bad = list(_secret_keys(cfg))
    if bad:  # never echo the values
        raise Refused(f"config holds secret-looking keys {bad}; pass secrets as env vars")
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise Refused(f"config misses {missing}")
    if not isinstance(cfg["run_id"], str) or not RUN_ID.fullmatch(cfg["run_id"]):
        raise Refused("run_id must match ^[a-z0-9][a-z0-9-]{0,40}$")
    if cfg["mode"] not in ("data-only", "full-site"):
        raise Refused("mode must be data-only or full-site")
    if not all(isinstance(cfg[k], list) for k in ("prod_cluster_uids", "scratch_cluster_uids")):
        raise Refused("prod_cluster_uids and scratch_cluster_uids must be lists")
    try:
        checks.parse_ts(cfg.get("incident_time"))
    except (ValueError, TypeError, AttributeError):
        raise Refused("incident_time must be ISO 8601 with a zone (Z or +00:00)") from None
    if "cnpg" in cfg:
        fp = Path(cfg["cnpg"].get("fingerprint", "fingerprint.json"))
        cfg["cnpg"]["fingerprint"] = str(fp if fp.is_absolute() else Path(path).parent / fp)
    return cfg


def parser():
    p = argparse.ArgumentParser(prog="styx_drtest.py", description=__doc__)
    p.add_argument("-c", "--config", required=True, help="drtest JSON config (no secrets)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="dry run: run the guards, print every write, change nothing")
    for name in ("run", "teardown"):
        sp = sub.add_parser(name)
        sp.add_argument("--confirm", required=True, metavar="RUN_ID")
    sp = sub.add_parser("fingerprint", help="read-only baseline of the source DB")
    sp.add_argument("--out", help="default: cnpg.fingerprint from the config")
    sp = sub.add_parser("mark", help="record a manual runbook step")
    sp.add_argument("step_id")
    sp.add_argument("event", choices=("start", "end"))
    sp.add_argument("--actor")
    sub.add_parser("report", help="rebuild report.json/report.md from the run dir")
    return p


def fingerprint(cfg, out, runner, sink):
    c = cfg["cnpg"]
    tables = checks.fingerprint_tables(runner, c["source"], c["tables"])
    errors = {t: v["error"] for t, v in tables.items() if "error" in v}
    if errors:
        sink.err(f"fingerprint failed: {errors}")
        return 1
    doc = {"taken_at": run.iso(run.now()), "server_name": c["server_name"], "tables": tables}
    sink.write(out, json.dumps(doc, indent=2))
    sink.out(f"fingerprint: {out} ({len(tables)} tables)")
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    sink = run.Sink()
    try:
        cfg = load_config(args.config)
        if getattr(args, "confirm", cfg["run_id"]) != cfg["run_id"]:
            raise Refused(f"--confirm must equal the run_id {cfg['run_id']!r}")
        runner = run.Runner(sink, dry=args.cmd == "plan")
        if args.cmd in ("plan", "run"):
            return run.execute(cfg, runner, sink)
        if args.cmd == "teardown":
            return run.teardown(cfg, runner)
        if args.cmd == "fingerprint":
            return fingerprint(cfg, args.out or cfg["cnpg"]["fingerprint"], runner, sink)
        if args.cmd == "mark":
            return run.mark(cfg, args.step_id, args.event, args.actor, sink)
        rd = run.run_dir(cfg)
        if not rd.exists():
            raise Refused(f"no run directory for {cfg['run_id']}")
        return run.write_report(cfg, rd, sink)
    except (KeyError, TypeError, AttributeError) as e:
        sink.err(f"REFUSED: config error ({type(e).__name__}: {e})")
        return 2
    except Refused as e:
        sink.err(f"REFUSED: {e}")
        return 2
