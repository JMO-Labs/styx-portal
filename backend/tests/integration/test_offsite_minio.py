"""Real kopia + MinIO (Object Lock) round trip for offsite-export.sh (issue #13).

Opt-in: OFFSITE_IT=1 with `minio`, `mc` and `kopia` on PATH (CI job offsite-integration).
"""

import hashlib
import json
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("OFFSITE_IT") != "1", reason="OFFSITE_IT!=1")

SCRIPT = Path(__file__).resolve().parents[3] / "deploy/k8s/offsite-export/offsite-export.sh"
BUCKET = "offsite-it"
USER, KEY = "itadmin", "itadmin-" + secrets.token_hex(8)


def _port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sh(cmd, env, check=True):
    return subprocess.run(cmd, env=env, capture_output=True, text=True, check=check)


@pytest.fixture(scope="module")
def minio(tmp_path_factory):
    d = tmp_path_factory.mktemp("minio")
    port = _port()
    env = {**os.environ, "MINIO_ROOT_USER": USER, "MINIO_ROOT_PASSWORD": KEY,
           "MC_CONFIG_DIR": str(d / "mc"), "MC_HOST_it": f"http://{USER}:{KEY}@127.0.0.1:{port}"}
    proc = subprocess.Popen(["minio", "server", str(d / "data"), "--address",
                             f"127.0.0.1:{port}", "--console-address", f"127.0.0.1:{_port()}"],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urlopen(f"http://127.0.0.1:{port}/minio/health/live", timeout=1)  # noqa: S310
            break
        except OSError:
            time.sleep(0.2)
    _sh(["mc", "mb", "--with-lock", f"it/{BUCKET}"], env)
    yield port, env
    proc.terminate()
    proc.wait(timeout=20)


@pytest.fixture(scope="module")
def repo(minio, tmp_path_factory):
    port, menv = minio
    d = tmp_path_factory.mktemp("repo")
    root = d / "snapshots"
    tree = root / "homes" / "alice" / ".snap" / f"nightly-{time.strftime('%Y-%m-%d', time.gmtime())}" / "uuid-1"
    tree.mkdir(parents=True)
    for i in range(4):
        (tree / f"blob{i}.bin").write_bytes(os.urandom(1 << 20))
    (tree / "notes.txt").write_text("v1\n")
    env = {**menv, "KOPIA_PASSWORD": secrets.token_urlsafe(32),
           "KOPIA_CONFIG_PATH": str(d / "cfg" / "repo.config"),
           "KOPIA_CACHE_DIRECTORY": str(d / "cache"), "KOPIA_LOG_DIR": str(d / "logs"),
           "KOPIA_CHECK_FOR_UPDATES": "false",
           "AWS_ACCESS_KEY_ID": USER, "AWS_SECRET_ACCESS_KEY": KEY,
           "OFFSITE_CIPHER": "AES256-GCM-HMAC-SHA256",
           "OFFSITE_S3_ENDPOINT": f"127.0.0.1:{port}", "OFFSITE_S3_BUCKET": BUCKET,
           "OFFSITE_S3_PREFIX": "styx/", "OFFSITE_S3_REGION": "us-east-1",
           "OFFSITE_S3_DISABLE_TLS": "true",
           "OFFSITE_KEEP_DAILY": "30", "OFFSITE_KEEP_WEEKLY": "8", "OFFSITE_KEEP_MONTHLY": "12",
           "OFFSITE_LOCK_DAYS": "35", "OFFSITE_SNAP_ROOT": str(root),
           "OFFSITE_SNAP_PREFIX": "nightly-", "OFFSITE_VERIFY_PERCENT": "100",
           "OFFSITE_FULL_VERIFY_DOW": time.strftime("%u", time.gmtime())}
    for mode in ("init", "export"):
        r = _sh(["sh", str(SCRIPT), mode], env, check=False)
        assert r.returncode == 0, (mode, r.stderr[-2000:])
    return env, tree


def _bucket_bytes(env):
    out = _sh(["mc", "du", "--versions", "--json", f"it/{BUCKET}"], env).stdout
    return json.loads(out.splitlines()[-1])["size"]


def _hashes(d):
    return {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(d).rglob("*")) if p.is_file()}


def _latest(env):
    out = _sh(["kopia", "snapshot", "list", "styx@offsite:/export/homes/alice", "--json"],
              env).stdout
    return json.loads(out)[-1]


def test_backup_verify_restore_roundtrip(repo, tmp_path):
    env, tree = repo
    r = _sh(["sh", str(SCRIPT), "verify"], env, check=False)
    assert r.returncode == 0, r.stderr[-2000:]
    dest = tmp_path / "restore"
    _sh(["kopia", "snapshot", "restore", _latest(env)["id"], str(dest)], env)
    assert _hashes(dest) == _hashes(tree)


def test_second_export_is_incremental(repo):
    env, tree = repo
    before = _bucket_bytes(env)
    (tree / "notes.txt").write_text("v2\n")
    r = _sh(["sh", str(SCRIPT), "export"], env, check=False)
    assert r.returncode == 0, r.stderr[-2000:]
    snaps = json.loads(_sh(["kopia", "snapshot", "list", "styx@offsite:/export/homes/alice",
                            "--json"], env).stdout)
    assert len(snaps) == 2
    assert snaps[-1]["stats"]["nonCachedFiles"] <= 1
    assert _bucket_bytes(env) - before < before / 10


def test_locked_object_delete_refused(repo):
    env, _ = repo
    out = _sh(["mc", "ls", "--recursive", "--versions", "--json", f"it/{BUCKET}/styx/"],
              env).stdout
    # Pack blobs (p*) hold the data; kopia leaves _log_/kopia.maintenance unlocked by design.
    objs = [json.loads(line) for line in out.splitlines() if '"key"' in line]
    obj = next(o for o in objs if o["key"].startswith("p"))
    r = _sh(["mc", "rm", "--version-id", obj["versionId"], f"it/{BUCKET}/styx/{obj['key']}"],
            env, check=False)
    assert r.returncode != 0
    after = _sh(["mc", "ls", "--versions", f"it/{BUCKET}/styx/{obj['key']}"], env).stdout
    assert obj["versionId"] in after


def test_wrong_password_cannot_connect(repo, tmp_path):
    env, _ = repo
    bad = {**env, "KOPIA_PASSWORD": secrets.token_urlsafe(32),
           "KOPIA_CONFIG_PATH": str(tmp_path / "other.config")}
    r = _sh(["sh", str(SCRIPT), "verify"], bad, check=False)
    assert r.returncode != 0


def test_orphaned_source_is_purged(repo, tmp_path):
    """A deleted user's source gets no new snapshots, so Kopia retention never expires it."""
    env, tree = repo
    for gs, start in (("homes/gone", "2020-01-02 03:04:05 UTC"),
                      ("homes/recent", time.strftime("%Y-%m-%d 00:00:00 UTC", time.gmtime()))):
        _sh(["kopia", "snapshot", "create", str(tree), f"--override-source=styx@offsite:/export/{gs}",
             f"--start-time={start}", f"--end-time={start}"], env)
    r = _sh(["sh", str(SCRIPT), "export"], env, check=False)
    assert r.returncode == 0, r.stderr[-2000:]
    out = _sh(["kopia", "snapshot", "list", "--all", "--json"], env).stdout
    paths = {s["source"]["path"] for s in json.loads(out)}
    assert paths == {"/export/homes/alice", "/export/homes/recent"}
