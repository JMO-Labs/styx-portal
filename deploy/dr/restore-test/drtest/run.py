"""Phase runner: redacting output sink, subprocess runner, step log, plan/run/teardown."""

import json
import os
import re
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import checks, guards, report
from .restorers import cnpg, kopia, velero

SECRET_ENV = re.compile(r"PASS|SECRET|TOKEN|ACCESS_KEY|KEY_ID|CREDENTIAL", re.I)


def now():
    return datetime.now(UTC)


def iso(t):
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")


class Sink:
    """Every byte the harness prints or writes passes through here, secrets replaced."""

    def __init__(self, env=None):
        env = os.environ if env is None else env
        vals = {v for k, v in env.items() if SECRET_ENV.search(k) and len(v) >= 4}
        # Also the forms json.dumps writes (", backslash and non-ASCII escaped).
        vals |= {json.dumps(v, ensure_ascii=a)[1:-1] for v in vals for a in (True, False)}
        self.secrets = sorted(vals, key=len, reverse=True)

    def redact(self, s):
        for v in self.secrets:
            s = s.replace(v, "***")
        return s

    def out(self, msg):
        print(self.redact(msg), flush=True)

    def err(self, msg):
        print(self.redact(msg), file=sys.stderr, flush=True)

    def write(self, path, text):
        Path(path).write_text(self.redact(text))

    def append(self, path, record):
        with open(path, "a") as f:
            f.write(self.redact(json.dumps(record, sort_keys=True)) + "\n")


class StepFailed(Exception):
    """A write step exited non-zero: stop before anything else is written."""


class Runner:
    """argv-only subprocess calls (never a shell). Writes are refused until armed;
    in dry mode they are printed instead of run."""

    def __init__(self, sink, dry=False):
        self.sink, self.dry, self.armed = sink, dry, False
        self.log, self.pending = None, []

    def attach(self, path):
        self.log = path
        for r in self.pending:
            self.sink.append(path, r)
        self.pending = []

    def __call__(self, argv, *, step, write=False, input=None, binary=False, env=None):
        cmd = shlex.join(argv)
        if write and not self.armed:
            raise RuntimeError(f"write before guards passed: {self.sink.redact(cmd)}")
        if write and self.dry:
            self.sink.out(f"$ {cmd}" + (f"\n{input}" if input else ""))
            return subprocess.CompletedProcess(argv, 0, b"" if binary else "", "")
        start = now()
        try:
            p = subprocess.run(argv, input=input, capture_output=True, text=not binary,
                               env={**os.environ, **(env or {})}, check=False)
        except FileNotFoundError:
            p = subprocess.CompletedProcess(argv, 127, b"" if binary else "", f"{argv[0]}: "
                                            "not found")
        rec = {"id": step, "start": iso(start), "end": iso(now()), "actor": "harness",
               "command": self.sink.redact(cmd),
               "result": "ok" if p.returncode == 0 else f"exit {p.returncode}"}
        if self.log:
            self.sink.append(self.log, rec)
        elif not self.dry:
            self.pending.append(rec)
        if write and p.returncode != 0:
            raise StepFailed(f"{step} failed ({rec['result']}): {rec['command']}")
        return p


def run_dir(cfg):
    """evidence/dr/<YYYY-MM-DD>-<run-id>; reuses the dir of an earlier mark or run."""
    root = Path(cfg["evidence_root"])
    found = sorted(root.glob(f"????-??-??-{cfg['run_id']}"))
    return found[-1] if found else root / f"{now():%Y-%m-%d}-{cfg['run_id']}"


def scratch_namespaces(cfg):
    nss = [cfg["namespace"]] + (guards.velero_targets(cfg) if "velero" in cfg else [])
    return list(dict.fromkeys(nss))


def guard_all(cfg, runner):
    """All guards; reads only. Local checks first, then the cluster reads."""
    nss = scratch_namespaces(cfg)
    for ns in nss:
        guards.namespace_name(ns)
    # Build every write command and SQL up front so config errors refuse before any write.
    if "cnpg" in cfg:
        cnpg.manifests(cfg)
        cnpg.restored_conn(cfg)
        for table, pk in cfg["cnpg"]["tables"].items():
            checks.fingerprint_sql(table, pk)
        if not runner.dry:
            cnpg.require_env()
    if "velero" in cfg:
        velero.restore_argv(cfg)
    if "kopia" in cfg:
        guards.kopia_targets(cfg)
        kopia.connect_argv(cfg, Path("kopia.config"))
    uid = guards.cluster(cfg, runner)
    existing = {ns: guards.namespace(ns, cfg["run_id"], runner) for ns in nss}
    if "velero" in cfg:
        guards.velero_bsl(cfg, runner)
    return uid, existing


def execute(cfg, runner, sink):
    """plan (runner.dry) or run. Returns the exit code."""
    started = now()
    uid, existing = guard_all(cfg, runner)
    rd = run_dir(cfg)
    if not runner.dry:
        rd.mkdir(parents=True, exist_ok=True)
        runner.attach(rd / "steps.jsonl")
    runner.armed = True
    try:
        snaps = restore(cfg, runner, rd, existing)
    except StepFailed as e:
        sink.err(f"ABORTED: {e}")
        write_report(cfg, rd, sink)  # no state.json: pass is false
        return 3
    if runner.dry:
        sink.out("# then: checks (row counts/checksums, pg_amcheck, alembic, velero phase, "
                 "kopia verify + sha256 sample, GET health_url), report, no teardown")
        return 0
    datasets = []
    if "cnpg" in cfg:
        datasets.append(cnpg.verify(cfg, runner))
    if "velero" in cfg:
        datasets.append(velero.verify(cfg, runner))
    if "kopia" in cfg:
        datasets += kopia.verify(cfg, runner, rd, snaps)
    c, t_end = checks.health(cfg["health_url"], cfg.get("health_attempts", 60),
                             cfg.get("health_interval_s", 10))
    datasets.append({"source": "app", "backup_id": None, "recovered_point": None,
                     "checks": [c]})
    state = {"started": iso(started), "t_end": iso(t_end) if t_end else None,
             "cluster_uid": uid, "datasets": datasets,
             "tool_versions": tool_versions(runner),
             "git_sha": runner(["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
                               step="git-sha").stdout.strip() or "unknown"}
    sink.write(rd / "state.json", json.dumps(state, indent=2))
    return write_report(cfg, rd, sink)


def restore(cfg, runner, rd, existing):
    """All write steps. A failed `create` may mean the namespace is someone else's."""
    for ns, ours in existing.items():
        if not ours:
            runner(["kubectl", "create", "-f", "-"], step="create-namespace", write=True,
                   input=json.dumps(guards.namespace_manifest(ns, cfg["run_id"]), indent=2))
    if "cnpg" in cfg:
        cnpg.restore(cfg, runner)
    if "velero" in cfg:
        velero.restore(cfg, runner)
    return kopia.restore(cfg, runner, rd) if "kopia" in cfg else {}


def tool_versions(runner):
    cmds = {"kubectl": ["kubectl", "version", "--client"],
            "velero": ["velero", "version", "--client-only"], "kopia": ["kopia", "--version"],
            "psql": ["psql", "--version"], "pg_amcheck": ["pg_amcheck", "--version"]}
    out = {}
    for name, argv in cmds.items():
        p = runner(argv, step="tool-version")
        out[name] = (p.stdout.strip().splitlines() or ["unknown"])[0]
    return out


def write_report(cfg, rd, sink):
    rep = report.build(cfg, rd)
    sink.write(rd / "report.json", json.dumps(rep, indent=2))
    sink.write(rd / "report.md", report.markdown(rep))
    sink.out(f"report: {rd / 'report.json'} pass={rep['pass']}")
    return 0 if rep["pass"] else 1


def mark(cfg, step_id, event, actor, sink):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", step_id):
        raise guards.Refused(f"bad step id {step_id!r}")
    rd = run_dir(cfg)
    rd.mkdir(parents=True, exist_ok=True)
    sink.append(rd / "steps.jsonl", {"id": step_id, "event": event, "time": iso(now()),
                                     "actor": actor or cfg.get("operator", "operator")})
    return 0


def teardown(cfg, runner):
    """Delete only namespaces that pass Guard 2 and carry this run's label."""
    nss = scratch_namespaces(cfg)
    for ns in nss:
        guards.namespace_name(ns)
    ours = [ns for ns in nss if guards.namespace(ns, cfg["run_id"], runner)]
    runner.armed = True
    sel = f"{guards.RUN_LABEL}={cfg['run_id']}"
    for ns in ours:
        runner(["kubectl", "delete", "namespace", "-l", sel, "--field-selector",
                f"metadata.name={ns}", "--wait=false"], step="teardown", write=True)
    return 0
