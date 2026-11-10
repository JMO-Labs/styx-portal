"""Nightly Raft snapshot CronJob to the offsite OpenBao prefix (issue #4, A1)."""

import re

from tests.openbao_checks import OPENBAO, check_images, check_security_context, load_docs


def one(name: str) -> dict:
    (doc,) = load_docs(OPENBAO / name)
    return doc


def pod() -> dict:
    return one("snapshot-cronjob.yaml")["spec"]["jobTemplate"]["spec"]["template"]["spec"]


def test_schedule_and_policy():
    cj = one("snapshot-cronjob.yaml")
    assert cj["metadata"] == {"name": "openbao-raft-snapshot", "namespace": "openbao"}
    assert cj["spec"]["schedule"] == "0 2 * * *"
    assert cj["spec"]["concurrencyPolicy"] == "Forbid"
    job = cj["spec"]["jobTemplate"]["spec"]
    assert job["backoffLimit"] == 2 and job["activeDeadlineSeconds"] > 0


def test_service_account():
    p = pod()
    assert p["serviceAccountName"] == "openbao-snapshot"
    assert p["automountServiceAccountToken"] is True
    sa = one("snapshot-sa.yaml")
    assert (sa["kind"], sa["metadata"]["name"], sa["metadata"]["namespace"]) == (
        "ServiceAccount", "openbao-snapshot", "openbao")
    kinds = {d["kind"] for f in OPENBAO.glob("*.yaml") if f.name != "values.yaml"
             for d in load_docs(f)}
    assert not kinds & {"Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"}


def test_init_container_saves_snapshot():
    (init,) = pod()["initContainers"]
    cmd = " ".join(init["command"] + init.get("args", []))
    assert re.search(r"operator raft snapshot save \"?/snap/openbao-", cmd)
    assert "role=raft-snapshot" in cmd and "auth/kubernetes/login" in cmd
    assert "date -u" in cmd
    assert init["image"].startswith("harbor.example.internal/openbao/openbao:")
    env = {e["name"]: e.get("value") for e in init["env"]}
    assert env["BAO_ADDR"] == "https://openbao-active.openbao.svc:8200"
    assert env["BAO_CACERT"].startswith("/openbao/tls/")
    assert "BAO_SKIP_VERIFY" not in env


def test_upload_container_uses_params_and_secret():
    (up,) = pod()["containers"]
    sources = {k: v["name"] for e in up["envFrom"] for k, v in e.items()}
    assert sources == {"configMapRef": "openbao-snapshot-params",
                       "secretRef": "openbao-snapshot-s3"}
    cmd = " ".join(up["command"] + up.get("args", []))
    assert "$(BUCKET)" in cmd or "${BUCKET}" in cmd
    assert "$(PREFIX)" in cmd or "${PREFIX}" in cmd
    assert "sse" not in cmd.lower()
    params = one("snapshot-params.yaml")
    assert params["kind"] == "ConfigMap" and params["metadata"]["name"] == "openbao-snapshot-params"
    assert params["data"]["PREFIX"] == "openbao/"
    assert params["data"]["BUCKET"]


def test_external_secret():
    es = one("snapshot-externalsecret.yaml")
    assert es["kind"] == "ExternalSecret" and es["metadata"]["name"] == "openbao-snapshot-s3"
    assert es["spec"]["secretStoreRef"] == {"kind": "ClusterSecretStore", "name": "openbao"}
    assert es["spec"]["target"]["name"] == "openbao-snapshot-s3"
    assert {d["remoteRef"]["key"] for d in es["spec"]["data"]} == {"openbao/snapshot-s3"}


def test_security_context_and_images():
    p = pod()
    for c in p["initContainers"] + p["containers"]:
        assert check_security_context(p["securityContext"], c["securityContext"]) == [], c["name"]
    assert check_images(p) == []
    assert {"emptyDir"} <= {k for v in p["volumes"] for k in v if k != "name"}
    assert not any("hostPath" in v for v in p["volumes"])


def test_namespace_label():
    (ns,) = load_docs(OPENBAO / "namespace.yaml")
    assert ns["metadata"]["labels"]["styx.io/openbao-secrets"] == "true"
