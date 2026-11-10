"""offsite-export.sh against a fake kopia that logs argv (issue #13)."""

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/k8s/offsite-export/offsite-export.sh"
PASSWORD = "p" * 31 + "-SeCrEt"
FAKEBIN = Path(__file__).resolve().parent / "fixtures" / "fakebin"


def day(offset=0):
    return (datetime.now(UTC) + timedelta(days=offset)).strftime("%Y-%m-%d")


def snap(root, group, subvol, name):
    d = root / group / subvol / ".snap" / name / "uuid-1"
    d.mkdir(parents=True)
    (d / "f.txt").write_text("x")
    return d


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "snapshots"
    root.mkdir()
    return {
        "PATH": f"{FAKEBIN}:{os.environ['PATH']}",
        "FAKE_LOG": str(tmp_path / "kopia.log"),
        "KOPIA_PASSWORD": PASSWORD,
        "OFFSITE_CIPHER": "AES256-GCM-HMAC-SHA256",
        "OFFSITE_S3_ENDPOINT": "s3.example.invalid",
        "OFFSITE_S3_BUCKET": "bucket",
        "OFFSITE_S3_PREFIX": "styx/",
        "OFFSITE_S3_REGION": "us-gov-west-1",
        "OFFSITE_KEEP_DAILY": "30",
        "OFFSITE_KEEP_WEEKLY": "8",
        "OFFSITE_KEEP_MONTHLY": "12",
        "OFFSITE_LOCK_DAYS": "35",
        "OFFSITE_SNAP_ROOT": str(root),
        "OFFSITE_SNAP_PREFIX": "nightly-",
        "OFFSITE_VERIFY_PERCENT": "1",
        "OFFSITE_FULL_VERIFY_DOW": "7",
    }


def run(env, mode, **over):
    e = {**env, **over}
    return subprocess.run(["sh", str(SCRIPT), mode], env=e, capture_output=True, text=True)


def calls(env):
    p = Path(env["FAKE_LOG"])
    if not p.exists():
        return []
    return [rec.split("\n")[:-1] for rec in p.read_text().split("\036\n")[:-1]]


def creates(env):
    return [c for c in calls(env) if c[:2] == ["snapshot", "create"]]


def test_rejects_unknown_cipher(env):
    r = run(env, "init", OFFSITE_CIPHER="AES128-CTR")
    assert r.returncode != 0
    assert calls(env) == []


def test_rejects_missing_password(env):
    env.pop("KOPIA_PASSWORD")
    assert run(env, "export").returncode != 0
    assert calls(env) == []


def test_rejects_short_password(env):
    assert run(env, "export", KOPIA_PASSWORD="x" * 31).returncode != 0
    assert calls(env) == []


def test_rejects_unknown_mode(env):
    assert run(env, "prune").returncode != 0
    assert calls(env) == []


def test_password_never_printed(env):
    snap(Path(env["OFFSITE_SNAP_ROOT"]), "g", "u1", f"nightly-{day()}")
    for mode, fail in (("init", "repository connect"), ("export", "snapshot create"),
                       ("verify", "")):
        r = run(env, mode, FAKE_FAIL=fail)
        assert PASSWORD not in r.stdout + r.stderr, mode
    assert not any(PASSWORD in " ".join(c) for c in calls(env))


def test_init_sets_cipher_lock_and_retention(env):
    r = run(env, "init", OFFSITE_CIPHER="CHACHA20-POLY1305-HMAC-SHA256",
            FAKE_FAIL="repository connect")
    assert r.returncode == 0, r.stderr
    log = calls(env)
    (create,) = [c for c in log if c[:3] == ["repository", "create", "s3"]]
    for flag in ("--encryption=CHACHA20-POLY1305-HMAC-SHA256", "--retention-mode=COMPLIANCE",
                 "--retention-period=35d", "--bucket=bucket", "--prefix=styx/",
                 "--endpoint=s3.example.invalid", "--region=us-gov-west-1"):
        assert flag in create, flag
    assert "--disable-tls" not in create
    (maint,) = [c for c in log if c[:2] == ["maintenance", "set"]]
    assert "--extend-object-locks=true" in maint
    (pol,) = [c for c in log if c[:2] == ["policy", "set"]]
    for flag in ("--global", "--keep-daily=30", "--keep-weekly=8", "--keep-monthly=12"):
        assert flag in pol, flag
    assert log.index(create) < log.index(maint) < log.index(pol)


def test_init_refuses_existing_repo(env):
    r = run(env, "init")
    assert r.returncode != 0
    assert not [c for c in calls(env) if c[:2] == ["repository", "create"]]


def test_export_picks_newest_snapshot_with_stable_source(env):
    root = Path(env["OFFSITE_SNAP_ROOT"])
    snap(root, "homes", "alice", f"nightly-{day(-1)}")
    new = snap(root, "homes", "alice", f"nightly-{day()}")
    r = run(env, "export")
    assert r.returncode == 0, r.stderr
    assert calls(env)[0][:3] == ["repository", "connect", "s3"]
    (c,) = creates(env)
    assert c[2] == str(new)
    assert "--override-source=styx@offsite:/export/homes/alice" in c
    assert f"--tags=snap:nightly-{day()}" in c


def test_export_fails_with_zero_snapshots(env):
    r = run(env, "export")
    assert r.returncode != 0
    assert creates(env) == []


def test_export_fails_on_stale_snapshot(env):
    snap(Path(env["OFFSITE_SNAP_ROOT"]), "homes", "alice", f"nightly-{day(-3)}")
    r = run(env, "export")
    assert r.returncode != 0
    assert "homes/alice" in r.stderr


def test_export_accepts_yesterday(env):
    snap(Path(env["OFFSITE_SNAP_ROOT"]), "homes", "alice", f"nightly-{day(-1)}")
    assert run(env, "export").returncode == 0


def test_export_ignores_foreign_snapshot_names(env):
    root = Path(env["OFFSITE_SNAP_ROOT"])
    good = snap(root, "homes", "alice", f"nightly-{day()}")
    snap(root, "homes", "alice", "manual-x")
    snap(root, "homes", "alice", "nightly-zzzz")
    assert run(env, "export").returncode == 0
    (c,) = creates(env)
    assert c[2] == str(good)


def test_export_continues_after_one_failure(env):
    root = Path(env["OFFSITE_SNAP_ROOT"])
    for u in ("u1", "u2", "u3"):
        snap(root, "homes", u, f"nightly-{day()}")
    r = run(env, "export", FAKE_FAIL="snapshot create .*/homes/u2/")
    assert r.returncode != 0
    assert len(creates(env)) == 3
    assert "homes/u2" in r.stderr
    assert "homes/u1" not in r.stderr.split("failed")[-1]


def test_verify_daily_and_weekly(env):
    today = datetime.now(UTC).isoweekday()
    r = run(env, "verify", OFFSITE_FULL_VERIFY_DOW=str(today))
    assert r.returncode == 0, r.stderr
    log = calls(env)
    assert log[0][:3] == ["repository", "connect", "s3"]
    (v,) = [c for c in log if c[:2] == ["snapshot", "verify"]]
    assert "--verify-files-percent=1" in v and "--file-parallelism=8" in v
    assert [c for c in log if c[:2] == ["content", "verify"]]
    Path(env["FAKE_LOG"]).unlink()
    assert run(env, "verify", OFFSITE_FULL_VERIFY_DOW=str(today % 7 + 1)).returncode == 0
    assert not [c for c in calls(env) if c[:2] == ["content", "verify"]]


def test_verify_failure_exits_nonzero(env):
    assert run(env, "verify", FAKE_FAIL="snapshot verify").returncode != 0


def test_paths_with_spaces(env):
    new = snap(Path(env["OFFSITE_SNAP_ROOT"]), "homes", "jane doe", f"nightly-{day()}")
    assert run(env, "export").returncode == 0
    (c,) = creates(env)
    assert c[2] == str(new)
    assert "--override-source=styx@offsite:/export/homes/jane doe" in c


def test_export_skips_ceph_internal_dirs(env):
    root = Path(env["OFFSITE_SNAP_ROOT"])
    good = snap(root, "homes", "alice", f"nightly-{day()}")
    (root / "_deleting" / "abc").mkdir(parents=True)
    (root / "_index" / "clone").mkdir(parents=True)
    r = run(env, "export")
    assert r.returncode == 0, r.stderr
    (c,) = creates(env)
    assert c[2] == str(good)


def test_export_includes_nogroup(env):
    new = snap(Path(env["OFFSITE_SNAP_ROOT"]), "_nogroup", "bob", f"nightly-{day()}")
    assert run(env, "export").returncode == 0
    (c,) = creates(env)
    assert c[2] == str(new)


def test_export_limits_to_configured_groups(env):
    root = Path(env["OFFSITE_SNAP_ROOT"])
    snap(root, "homes", "alice", f"nightly-{day()}")
    snap(root, "profiles", "alice", f"nightly-{day()}")
    (root / "csi" / "pvc-1").mkdir(parents=True)
    r = run(env, "export", OFFSITE_GROUPS="homes profiles")
    assert r.returncode == 0, r.stderr
    assert len(creates(env)) == 2


@pytest.mark.parametrize("bogus", ["nightly-2099-01-01", "nightly-2026-13-45", "nightly-2026-02-30"])
def test_export_ignores_future_or_invalid_dates(env, bogus):
    root = Path(env["OFFSITE_SNAP_ROOT"])
    good = snap(root, "homes", "alice", f"nightly-{day()}")
    snap(root, "homes", "alice", bogus)
    r = run(env, "export")
    assert r.returncode == 0, r.stderr
    (c,) = creates(env)
    assert c[2] == str(good)


def test_export_only_bogus_dates_fails(env):
    snap(Path(env["OFFSITE_SNAP_ROOT"]), "homes", "alice", "nightly-2099-01-01")
    r = run(env, "export")
    assert r.returncode != 0
    assert creates(env) == []
