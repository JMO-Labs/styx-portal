"""Kopia offsite repo (#13): read-only connect, restore newest snapshot per source (Guard 5)."""

import json

from .. import checks
from ..checks import check


def base(rd):
    # Own config file per run so the operator's default kopia connection is never touched.
    return ["kopia", f"--config-file={rd / 'kopia.config'}"]


def connect_argv(cfg, config_file):
    s = cfg["kopia"]["s3"]
    argv = ["kopia", f"--config-file={config_file}", "repository", "connect", "s3",
            f"--bucket={s['bucket']}", f"--endpoint={s['endpoint']}",
            f"--prefix={s.get('prefix', '')}"]
    if s.get("region"):
        argv.append(f"--region={s['region']}")
    if s.get("disable_tls"):
        argv.append("--disable-tls")
    # KOPIA_PASSWORD and AWS_* come from the environment, never argv, and are not persisted.
    return argv + ["--readonly", "--no-persist-credentials"]


def restore(cfg, runner, rd):
    """Returns {source: newest snapshot manifest or None}."""
    k = base(rd)
    runner(connect_argv(cfg, rd / "kopia.config"), step="kopia-connect", write=True)
    snaps = {}
    for s in cfg["kopia"]["sources"]:
        src = s["source"]
        if runner.dry:
            runner([*k, "snapshot", "restore", f"<newest snapshot of {src}>", s["target"]],
                   step="kopia-restore", write=True)
            continue
        p = runner([*k, "snapshot", "list", src, "--json"], step="kopia-list")
        try:
            items = json.loads(p.stdout) if p.returncode == 0 else []
        except ValueError:
            items = []
        newest = max(items, key=lambda x: x["startTime"], default=None)
        snaps[src] = newest
        if newest:
            runner([*k, "snapshot", "restore", newest["id"], s["target"]],
                   step="kopia-restore", write=True)
    return snaps


def verify_snapshot(runner, k, snap_id):
    p = runner([*k, "snapshot", "verify", "--verify-files-percent=100", snap_id],
               step="kopia-verify")
    return check(f"kopia:verify:{snap_id}", p.returncode == 0,
                 "ok" if p.returncode == 0 else p.stderr.strip()[-300:])


def verify(cfg, runner, rd, snaps):
    k = base(rd)
    out = []
    for s in cfg["kopia"]["sources"]:
        src, snap = s["source"], snaps.get(s["source"])
        if not snap:
            res = [check(f"kopia:snapshot:{src}", False, "no snapshot found")]
        else:
            res = [verify_snapshot(runner, k, snap["id"]),
                   checks.sha256_sample(runner, k, snap["rootEntry"]["obj"], s["target"],
                                        cfg["kopia"].get("sample", 20), cfg["run_id"])]
        out.append({"source": f"kopia:{src}", "backup_id": snap["id"] if snap else None,
                    "recovered_point": snap["startTime"] if snap else None, "checks": res})
    return out
