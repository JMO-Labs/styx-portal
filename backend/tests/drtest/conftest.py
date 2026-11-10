"""Fixtures for the DR restore test harness (issue #15): fake binaries on PATH + config."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[3] / "deploy/dr/restore-test"
sys.path.insert(0, str(HARNESS))
FAKEBIN = Path(__file__).resolve().parents[1] / "fixtures" / "fakebin"

RUN, NS, UID = "t1", "styx-drtest-t1", "uid-scratch"
SECRETS = {
    "PGPASSWORD": "pg-SENTINEL-9f3a",
    "KOPIA_PASSWORD": "kopia-SENTINEL-77b1",
    "AWS_ACCESS_KEY_ID": "AKIASENTINEL0001",
    "AWS_SECRET_ACCESS_KEY": "aws-SENTINEL-c0ffee",
    "DRTEST_CNPG_S3_KEY_ID": "cnpgSENTINELid",
    "DRTEST_CNPG_S3_SECRET": "cnpg-SENTINEL-secret",
}
WRITE_WORDS = {"create", "apply", "restore", "delete", "patch", "label", "wait"}
READ_WORDS = {"get", "version", "describe"}
BACKUP = {"spec": {"storageLocation": "dr-ro"},
          "status": {"startTimestamp": "2026-11-09T02:00:00Z"}}


def base_cfg(tmp):
    root = tmp / "scratch"
    root.mkdir(exist_ok=True)
    return {
        "run_id": RUN, "mode": "data-only", "namespace": NS,
        "prod_cluster_uids": ["uid-prod"], "scratch_cluster_uids": [],
        "operator": "op", "witness": "wit", "rto_clock_start": "harness start",
        "incident_time": None, "evidence_root": str(tmp / "evidence/dr"),
        "alembic_head": "head1", "health_url": "http://127.0.0.1:1/api/health",
        "health_attempts": 1, "health_interval_s": 0,
        "cnpg": {
            "server_name": "styx-db", "cluster_name": "styx-drtest-db",
            "object_store": {"destination_path": "s3://cnpg/", "endpoint_url": "https://s3.x"},
            "target_time": None, "storage_size": "1Gi",
            "source": {"host": "src", "port": 5432, "user": "ro", "dbname": "styx"},
            "restored": {"host": "dst", "port": 5432, "user": "app", "dbname": "styx"},
            "tables": {"users": "id", "groups": "id"},
            "fingerprint": str(tmp / "fingerprint.json"),
        },
        "velero": {
            "namespace": "velero", "backup": "styx-daily", "prod_bsl": "default",
            "include_namespaces": ["styx"], "namespace_mappings": {"styx": NS},
        },
        "kopia": {
            "s3": {"bucket": "b", "endpoint": "s3.x", "prefix": "styx/"},
            "scratch_mount_root": str(root), "sample": 5,
            "sources": [{"source": "styx@offsite:/export/homes/alice",
                         "target": str(root / "alice")}],
        },
    }


class Harness:
    def __init__(self, tmp):
        self.tmp = tmp
        self.log = tmp / "argv.log"
        self.rules = []
        self.cfg = base_cfg(tmp)
        self.n = 0
        # Defaults for a clean scratch target; on() prepends so tests override them.
        self.on(r"^kubectl get namespace kube-system", out=UID)
        self.on(r"^kubectl get namespace styx-drtest", code=1)
        self.on(r"^velero backup get", out=json.dumps(BACKUP))
        self.on(r"^kubectl get backupstoragelocations", out='{"spec":{"accessMode":"ReadOnly"}}')

    def on(self, regex, out=None, code=0):
        path = ""
        if out is not None:
            self.n += 1
            p = self.tmp / f"out{self.n}"
            p.write_bytes(out if isinstance(out, bytes) else (out + "\n").encode())
            path = str(p)
        self.rules.insert(0, f"{regex}\t{code}\t{path}")

    def env(self, **over):
        rules = self.tmp / "rules.tsv"
        rules.write_text("\n".join(self.rules) + "\n")
        env = {k: v for k, v in os.environ.items() if k not in SECRETS}
        return {**env, **SECRETS, "PATH": f"{FAKEBIN}:{env['PATH']}",
                "FAKE_LOG": str(self.log), "FAKE_RULES": str(rules), **over}

    def cli(self, *args, **env_over):
        cfg = self.tmp / "drtest.json"
        cfg.write_text(json.dumps(self.cfg))
        return subprocess.run(
            [sys.executable, str(HARNESS / "styx_drtest.py"), "-c", str(cfg), *args],
            env=self.env(**env_over), cwd=self.tmp, capture_output=True, text=True)

    def calls(self):
        if not self.log.exists():
            return []
        return [r.split("\n")[:-1] for r in self.log.read_text().split("\036\n")[:-1]]

    def writes(self):
        return [c for c in self.calls() if WRITE_WORDS & set(c)]

    def only_reads(self):
        return all(READ_WORDS & set(c) and not WRITE_WORDS & set(c) for c in self.calls())

    def run_dir(self):
        return next((self.tmp / "evidence/dr").glob(f"*-{RUN}"))


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


@pytest.fixture
def fake_env(h, monkeypatch):
    """Point in-process subprocess calls at the fakes; returns the Harness."""
    def apply():
        for k, v in h.env().items():
            monkeypatch.setenv(k, v)
    h.apply = apply
    apply()
    return h


@pytest.fixture
def health():
    """Local /api/health; set health.code to change the reply."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(srv.code)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    srv.code = 200
    srv.url = f"http://127.0.0.1:{srv.server_port}/api/health"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def full_run_setup(h, health):
    """Rules + files for a complete passing fake run."""
    h.cfg["health_url"] = health.url
    h.cfg["incident_time"] = h.cfg["incident_time"] or "2026-11-09T12:00:00Z"
    (h.tmp / "fingerprint.json").write_text(json.dumps({
        "taken_at": "2026-11-09T03:00:00Z",
        "tables": {"users": {"count": 3, "md5": "aaa"}, "groups": {"count": 1, "md5": "bbb"}}}))
    h.on(r"^psql .*FROM \"users\"", out="3|aaa")
    h.on(r"^psql .*FROM \"groups\"", out="1|bbb")
    h.on(r"^psql .*alembic_version", out="head1")
    h.on(r"^psql .*pg_last_xact_replay_timestamp", out="2026-11-09 03:00:00+00")
    h.on(r"^velero restore get", out='{"status":{"phase":"Completed","errors":0}}')
    snap = [{"id": "s1", "startTime": "2026-11-09T01:00:00Z", "rootEntry": {"obj": "k123"}},
            {"id": "s0", "startTime": "2026-11-08T01:00:00Z", "rootEntry": {"obj": "k000"}}]
    h.on(r"^kopia .*snapshot list", out=json.dumps(snap))
    h.on(r"^kopia .*show k123/a.txt", out=b"hello\n")
    alice = Path(h.cfg["kopia"]["sources"][0]["target"])
    alice.mkdir(parents=True, exist_ok=True)
    (alice / "a.txt").write_bytes(b"hello\n")
