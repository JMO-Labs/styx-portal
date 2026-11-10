"""Velero: namespace-mapped restore, never cluster-scoped resources (Guard 3)."""

import json

from ..checks import check
from ..guards import RUN_LABEL


def _ns(cfg):
    return cfg["velero"].get("namespace", "velero")


def restore_name(cfg):
    return f"styx-drtest-{cfg['run_id']}"


def restore_argv(cfg):
    v = cfg["velero"]
    inc = v["include_namespaces"]
    maps = ",".join(f"{n}:{v['namespace_mappings'][n]}" for n in inc)
    return ["velero", "restore", "create", restore_name(cfg), "--from-backup", v["backup"],
            "--include-namespaces", ",".join(inc), "--namespace-mappings", maps,
            "--include-cluster-resources=false", "--labels", f"{RUN_LABEL}={cfg['run_id']}",
            "--wait", "-n", _ns(cfg)]


def restore(cfg, runner):
    runner(restore_argv(cfg), step="velero-restore", write=True)


def _get(runner, argv, step):
    p = runner(argv, step=step)
    try:
        d = json.loads(p.stdout) if p.returncode == 0 else {}
    except ValueError:
        d = {}
    return (d.get("items") or [d])[0] if isinstance(d, dict) else {}


def verify(cfg, runner):
    r = _get(runner, ["velero", "restore", "get", restore_name(cfg), "-n", _ns(cfg), "-o",
                      "json"], "velero-restore-get")
    st = r.get("status") or {}
    phase, errors = st.get("phase"), st.get("errors", 0)
    ok = phase == "Completed" and not errors
    b = _get(runner, ["velero", "backup", "get", cfg["velero"]["backup"], "-n", _ns(cfg), "-o",
                      "json"], "velero-backup-get")
    return {"source": "velero", "backup_id": cfg["velero"]["backup"],
            "recovered_point": (b.get("status") or {}).get("startTimestamp"),
            "checks": [check("velero:restore-phase", ok,
                             f"phase={phase} errors={errors} warnings={st.get('warnings', 0)}")]}
