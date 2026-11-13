"""Home cold-storage archive IaC: RGW bucket + object lock + backend wiring (#267)."""

import json
from pathlib import Path

import yaml

ENT = Path(__file__).resolve().parents[2] / "deploy/enterprise"
ARCHIVE = ENT / "rook-ceph/home-archive.yaml"


def _docs():
    return [d for d in yaml.safe_load_all(ARCHIVE.read_text()) if d]


def _kind(kind):
    return next(d for d in _docs() if d["kind"] == kind)


def _job_text():
    return json.dumps(_kind("Job"))


def test_listed_in_kustomization():
    k = yaml.safe_load((ENT / "rook-ceph/kustomization.yaml").read_text())
    assert "home-archive.yaml" in k["resources"]


def test_object_user_on_styx_store():
    u = _kind("CephObjectStoreUser")
    assert u["spec"]["store"] == "styx-store"
    assert u["metadata"]["namespace"] == "rook-ceph"


def test_bucket_bootstrap_job_object_lock_and_retention():
    j = _job_text()
    assert "styx-home-archive" in j
    assert "--object-lock-enabled-for-bucket" in j
    assert "put-object-lock-configuration" in j
    assert '"Mode":"GOVERNANCE"' in j.replace("\\", "").replace(" ", "")
    assert '"Days":30' in j.replace("\\", "").replace(" ", "")


def test_lifecycle_expires_noncurrent_versions():
    j = _job_text()
    assert "put-bucket-lifecycle-configuration" in j
    assert "NoncurrentVersionExpiration" in j


def test_job_credentials_from_secret_ref():
    j = _kind("Job")
    env = j["spec"]["template"]["spec"]["containers"][0]["env"]
    refs = [e for e in env if "secretKeyRef" in e.get("valueFrom", {})]
    assert {e["name"] for e in refs} >= {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}
    assert all("value" not in e for e in refs)


def _backend():
    p = yaml.safe_load((ENT / "backend-patch.yaml").read_text())
    return p["spec"]["template"]["spec"]


def test_backend_archive_env_from_secret():
    env = {e["name"]: e for e in _backend()["containers"][0]["env"]}
    assert "ARCHIVE_S3_ENDPOINT" in env
    assert env["ARCHIVE_S3_BUCKET"]["value"] == "styx-home-archive"
    for n in ("ARCHIVE_S3_ACCESS_KEY", "ARCHIVE_S3_SECRET_KEY"):
        assert "secretKeyRef" in env[n]["valueFrom"]
        assert "value" not in env[n]
    assert env["HOMES_ROOT"]["value"] == "/homes"


def test_backend_mounts_homes():
    spec = _backend()
    mounts = {m["mountPath"]: m for m in spec["containers"][0]["volumeMounts"]}
    assert "/homes" in mounts
    vol = next(v for v in spec["volumes"] if v["name"] == mounts["/homes"]["name"])
    assert "persistentVolumeClaim" in vol
