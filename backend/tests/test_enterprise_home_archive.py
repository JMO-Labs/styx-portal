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


def _all_docs():
    out = []
    for p in ENT.rglob("*.yaml"):
        try:
            out += [d for d in yaml.safe_load_all(p.read_text()) if isinstance(d, dict)]
        except yaml.YAMLError:
            continue
    return out


def _find(kind, name, ns=None):
    return next(
        (d for d in _all_docs() if d.get("kind") == kind
         and d["metadata"].get("name") == name
         and (ns is None or d["metadata"].get("namespace") == ns)),
        None,
    )


BRIDGE = ENT / "archive-s3-credentials.yaml"


def test_backend_archive_secret_is_produced():
    env = {e["name"]: e for e in _backend()["containers"][0]["env"]}
    name = env["ARCHIVE_S3_ACCESS_KEY"]["valueFrom"]["secretKeyRef"]["name"]
    es = next(d for d in yaml.safe_load_all(BRIDGE.read_text())
              if d["kind"] == "ExternalSecret")
    assert es["metadata"]["namespace"] == "styx"
    assert es["spec"]["target"]["name"] == name
    keys = {d["secretKey"] for d in es["spec"]["data"]}
    assert keys == {"AccessKey", "SecretKey"}
    assert {d["remoteRef"]["key"] for d in es["spec"]["data"]} == {
        "rook-ceph-object-user-styx-store-styx-archive"}
    k = yaml.safe_load((ENT / "kustomization.yaml").read_text())
    assert BRIDGE.name in k["resources"]


def test_archive_secret_reader_is_least_privilege():
    docs = list(yaml.safe_load_all(BRIDGE.read_text()))
    role = next(d for d in docs if d["kind"] == "Role")
    assert role["metadata"]["namespace"] == "rook-ceph"
    assert role["rules"] == [{
        "apiGroups": [""], "resources": ["secrets"],
        "resourceNames": ["rook-ceph-object-user-styx-store-styx-archive"],
        "verbs": ["get"]}]
    store = next(d for d in docs if d["kind"] == "SecretStore")
    assert store["spec"]["provider"]["kubernetes"]["remoteNamespace"] == "rook-ceph"


def test_homes_claim_exists_rwx():
    spec = _backend()
    vol = next(v for v in spec["volumes"] if v["name"] == "homes")
    claim = vol["persistentVolumeClaim"]["claimName"]
    pvc = _find("PersistentVolumeClaim", claim, "styx")
    assert pvc is not None
    assert pvc["spec"]["accessModes"] == ["ReadWriteMany"]
    pv = _find("PersistentVolume", pvc["spec"]["volumeName"])
    assert pv["spec"]["accessModes"] == ["ReadWriteMany"]
    attrs = pv["spec"]["csi"]["volumeAttributes"]
    assert attrs["staticVolume"] == "true"
    assert attrs["fsName"] == "homes"
    assert attrs["rootPath"] == "/volumes/homes"
    k = yaml.safe_load((ENT / "kustomization.yaml").read_text())
    assert "homes-pv.yaml" in k["resources"]


def test_bootstrap_job_hardened():
    pod = _kind("Job")["spec"]["template"]["spec"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    c = pod["containers"][0]["securityContext"]
    assert c["runAsNonRoot"] is True
    assert c["seccompProfile"]["type"] == "RuntimeDefault"
    assert _kind("Job")["spec"]["ttlSecondsAfterFinished"] > 0
