import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
HOMELAB = DEPLOY / "k8s"
ENT = DEPLOY / "enterprise"

HOMELAB_ONLY = {
    ("CronJob", "styx-db-backup"),
    ("PersistentVolumeClaim", "styx-data"),
    ("PersistentVolumeClaim", "styx-backups"),
    ("StorageClass", "longhorn-styx"),
    ("Role", "styx-cloudflared-pods"),
    ("RoleBinding", "styx-cloudflared-pods"),
}


def _kustomization():
    return yaml.safe_load((ENT / "kustomization.yaml").read_text())


def _index():
    """Every YAML doc in deploy/enterprise/*.yaml (not kustomization) by (kind, name)."""
    out = {}
    for f in sorted(ENT.glob("*.yaml")):
        if f.name == "kustomization.yaml":
            continue
        for d in yaml.safe_load_all(f.read_text()):
            if d:
                out[(d["kind"], d["metadata"]["name"])] = d
    return out


def test_kustomization_bases_on_homelab():
    res = _kustomization()["resources"]
    assert "../k8s" in res
    for r in res:
        assert (ENT / r).exists(), r


def test_homelab_unchanged():
    (be,) = [d for d in yaml.safe_load_all((HOMELAB / "backend.yaml").read_text())
             if d["kind"] == "Deployment" and d["metadata"]["name"] == "backend"]
    assert be["spec"]["replicas"] == 1
    assert be["spec"]["strategy"]["type"] == "Recreate"
    listed = yaml.safe_load((HOMELAB / "kustomization.yaml").read_text())["resources"]
    assert "backup-cronjob.yaml" in listed and "pvc.yaml" in listed


def test_removes_homelab_only_resources():
    idx = _index()
    for key in HOMELAB_ONLY:
        assert key in idx, key
        assert idx[key]["$patch"] == "delete"


def test_no_secrets_committed():
    for f in ENT.glob("*.yaml"):
        for d in yaml.safe_load_all(f.read_text()):
            if d and d.get("kind") == "Secret":
                assert not d.get("data") and not d.get("stringData"), f.name


class _Loader(yaml.SafeLoader):
    """Kustomize emits bare `=` (matchType), a YAML 1.1 'value' tag in PyYAML."""


_Loader.add_constructor("tag:yaml.org,2002:value", lambda _loader, node: node.value)


def _build(path):
    tool = ["kustomize", "build"] if shutil.which("kustomize") else ["kubectl", "kustomize"]
    out = subprocess.run([*tool, str(path)], capture_output=True, text=True, check=True)
    return [d for d in yaml.load_all(out.stdout, Loader=_Loader) if d]


@pytest.mark.skipif(not (shutil.which("kustomize") or shutil.which("kubectl")),
                    reason="kustomize/kubectl not installed")
def test_kustomize_build():
    kinds = {(d["kind"], d["metadata"]["name"]) for d in _build(ENT)}
    assert not kinds & HOMELAB_ONLY
    assert not {k for k, _ in kinds} & {"CronJob", "PersistentVolumeClaim"}
    be = [d for d in _build(ENT) if d["kind"] == "Deployment" and d["metadata"]["name"] == "backend"]
    assert be[0]["spec"]["replicas"] == 3
    assert ("CronJob", "styx-db-backup") in {(d["kind"], d["metadata"]["name"])
                                             for d in _build(HOMELAB)}


def _of_kind(kind):
    return [d for (k, _), d in _index().items() if k == kind]


def test_db_secret_rotation():
    (gen,) = _of_kind("Password")
    assert gen["apiVersion"] == "generators.external-secrets.io/v1alpha1"
    (es,) = [d for d in _of_kind("ExternalSecret") if d["spec"]["target"]["name"] == "styx-db-app"]
    assert es["spec"]["refreshInterval"] == "720h"
    assert es["spec"]["dataFrom"][0]["sourceRef"]["generatorRef"]["kind"] == "Password"
    tpl = es["spec"]["target"]["template"]
    assert tpl["type"] == "kubernetes.io/basic-auth"
    assert tpl["metadata"]["labels"]["cnpg.io/reload"] == "true"
    assert tpl["data"]["username"] == "styx"
    assert tpl["data"]["pgpass"].startswith("styx-db-rw:5432:styx:styx:")
    assert "{{ .password }}" in tpl["data"]["pgpass"]
    assert es["spec"]["target"]["creationPolicy"] == "Merge"
    assert "IA-5" in (ENT / "db-credentials.yaml").read_text()


def test_password_generator_safe_charset():
    (gen,) = _of_kind("Password")
    spec = gen["spec"]
    assert spec["length"] >= 32
    if not spec.get("noSymbols"):
        assert not set(spec.get("symbolCharacters", "")) & set(":\\@/#?")


def test_jwt_secret_from_openbao():
    by_target = {d["spec"]["target"]["name"]: d for d in _of_kind("ExternalSecret")}
    for name in ("styx-secrets", "styx-db-bucket"):
        store = by_target[name]["spec"]["secretStoreRef"]
        assert (store["kind"], store["name"]) == ("ClusterSecretStore", "openbao")
    keys = {r["secretKey"] for r in by_target["styx-secrets"]["spec"]["data"]}
    assert "JWT_SECRET" in keys
    assert by_target["styx-secrets"]["spec"]["data"][0]["remoteRef"]["key"]
    assert {"SSE_C_KEY"} <= {r["secretKey"] for r in by_target["styx-db-bucket"]["spec"]["data"]}


def test_listed_in_kustomization():
    res = _kustomization()["resources"]
    assert "db-credentials.yaml" in res and "external-secrets.yaml" in res


def _walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def test_cluster_spec():
    c = _index()[("Cluster", "styx-db")]
    assert c["metadata"]["namespace"] == "styx"
    s = c["spec"]
    assert s["instances"] == 3
    assert s["imageName"].split(":")[1].split(".")[0].split("-")[0] == "17"
    assert s["enableSuperuserAccess"] is False
    aff = s["affinity"]
    assert aff["enablePodAntiAffinity"] is True
    assert aff["podAntiAffinityType"] == "required"
    assert aff["topologyKey"] == "kubernetes.io/hostname"
    init = s["bootstrap"]["initdb"]
    assert (init["database"], init["owner"], init["secret"]["name"]) == ("styx", "styx", "styx-db-app")
    assert s["postgresql"]["synchronous"] == {"method": "any", "number": 1, "dataDurability": "preferred"}
    assert "rook" in s["storage"]["storageClass"]
    assert s["plugins"] == [{"name": "barman-cloud.cloudnative-pg.io", "isWALArchiver": True,
                             "parameters": {"barmanObjectName": "styx-db-offsite"}}]
    assert s["backup"]["volumeSnapshot"]["className"]


def test_no_in_tree_barman():
    for f in ENT.glob("*.yaml"):
        for d in yaml.safe_load_all(f.read_text()):
            assert "barmanObjectStore" not in set(_walk(d)), f.name


def test_objectstore_retention_and_ssec():
    o = _index()[("ObjectStore", "styx-db-offsite")]
    assert o["apiVersion"] == "barmancloud.cnpg.io/v1"
    c = o["spec"]["configuration"]
    assert o["spec"]["retentionPolicy"] == "30d"
    assert c["destinationPath"]
    cr = c["s3Credentials"]
    for k in ("accessKeyId", "secretAccessKey", "sseCustomerKey"):
        assert cr[k]["name"] == "styx-db-bucket"
    assert c["wal"]["compression"] and c["data"]["compression"]


def test_two_scheduled_backups():
    sb = [d for (k, _), d in _index().items() if k == "ScheduledBackup"]
    assert {d["spec"]["method"] for d in sb} == {"plugin", "volumeSnapshot"}
    assert len(sb) == 2
    for d in sb:
        assert d["spec"]["cluster"]["name"] == "styx-db"
        assert d["spec"]["schedule"]
    plug = [d for d in sb if d["spec"]["method"] == "plugin"][0]
    assert plug["spec"]["pluginConfiguration"]["name"] == "barman-cloud.cloudnative-pg.io"


def _alerts(rule):
    return {r["alert"]: r for g in rule["spec"]["groups"] for r in g["rules"] if "alert" in r}


def test_backup_alerts_replaced():
    a = _alerts(_index()[("PrometheusRule", "styx")])
    assert not {"StyxBackupFailed", "StyxBackupStale"} & set(a)
    assert "StyxBackendDown" in a
    M = "barman_cloud_cloudnative_pg_io_last_available_backup_timestamp"
    assert any(M in r["expr"] and "93600" in r["expr"] and "absent(" in r["expr"]
               and "== 0" in r["expr"] for r in a.values())
    assert not any("cnpg_collector_last_available_backup_timestamp" in r["expr"] for r in a.values())
    assert any("barman_cloud_cloudnative_pg_io_last_failed_backup_timestamp" in r["expr"]
               and M in r["expr"] for r in a.values())
    assert any("increase(cnpg_pg_stat_archiver_failed_count" in r["expr"] for r in a.values())
    assert {"networkpolicy.yaml"} <= set(_kustomization()["resources"])
    assert "prometheusrule-patch.yaml" in [p["path"] for p in _kustomization()["patches"]]


def test_networkpolicy_db_operator_s3():
    idx = _index()
    ing = idx[("NetworkPolicy", "styx-db-ingress")]["spec"]["ingress"]
    ports = {(r["from"][0].get("podSelector", {}).get("matchLabels", {}).get("app"),
              r["from"][0].get("namespaceSelector", {}).get("matchLabels", {}).get("kubernetes.io/metadata.name"),
              r["ports"][0]["port"]) for r in ing}
    assert ("styx-backend", None, 5432) in ports
    assert (None, "cnpg-system", 8000) in ports
    eg = idx[("NetworkPolicy", "styx-db-egress")]["spec"]["egress"]
    assert any("ipBlock" in t for r in eg for t in r.get("to", []))


@pytest.mark.skipif(not (shutil.which("kustomize") or shutil.which("kubectl")),
                    reason="kustomize/kubectl not installed")
def test_kustomize_build_alerts():
    (r,) = [d for d in _build(ENT) if d["kind"] == "PrometheusRule"]
    assert "StyxBackupStale" not in _alerts(r)
    (h,) = [d for d in _build(HOMELAB) if d["kind"] == "PrometheusRule"]
    assert "StyxBackupStale" in _alerts(h)


def _backend():
    return _index()[("Deployment", "backend")]


def _pod():
    return _backend()["spec"]["template"]


def _container():
    (c,) = [c for c in _pod()["spec"]["containers"] if c["name"] == "backend"]
    return c


def _env():
    return {e["name"]: e.get("value") for e in _container()["env"]}


def test_backend_patch_multi_replica():
    spec = _backend()["spec"]
    assert spec["replicas"] == 3
    assert spec["strategy"] == {"type": "RollingUpdate",
                                "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0}}
    ann = _pod()["metadata"]["annotations"]
    assert ann["secret.reloader.stakater.com/reload"] == (
        "styx-db-app,styx-secrets,styx-matrix-notify,styx-archive-s3")
    (tsc,) = _pod()["spec"]["topologySpreadConstraints"]
    assert tsc["topologyKey"] == "kubernetes.io/hostname"
    assert _container()["startupProbe"]["failureThreshold"] == 60
    assert "backend-patch.yaml" in [p["path"] for p in _kustomization()["patches"]]
    assert "pdb.yaml" in _kustomization()["resources"]


def test_backend_db_urls_have_no_password():
    import re
    env = _env()
    for k in ("DATABASE_URL", "LEADER_DATABASE_URL"):
        url = env[k]
        assert url == "postgresql+asyncpg://styx@styx-db-rw:5432/styx?ssl=verify-full"
        assert not re.search(r"//[^:/@]+:[^@]*@", url)
        assert re.search(r"//[^:/@]+@", url)
    assert "pooler" not in env["LEADER_DATABASE_URL"]


def test_backend_mounts_pgpass_without_subpath():
    c, p = _container(), _pod()["spec"]
    mounts = {m["name"]: m for m in c["volumeMounts"]}
    vols = {v["name"]: v for v in p["volumes"]}
    for secret in ("styx-db-app", "styx-db-ca"):
        (v,) = [v for v in vols.values() if v.get("secret", {}).get("secretName") == secret]
        m = mounts[v["name"]]
        assert "subPath" not in m and "subPathExpr" not in m
    app_v = [v for v in vols.values() if v.get("secret", {}).get("secretName") == "styx-db-app"][0]
    ca_v = [v for v in vols.values() if v.get("secret", {}).get("secretName") == "styx-db-ca"][0]
    env = _env()
    assert env["PGPASSFILE"] == mounts[app_v["name"]]["mountPath"] + "/pgpass"
    assert env["PGSSLROOTCERT"] == mounts[ca_v["name"]]["mountPath"] + "/ca.crt"


def test_data_volume_is_emptydir():
    (v,) = [v for v in _pod()["spec"]["volumes"] if v["name"] == "data"]
    assert "emptyDir" in v and v.get("persistentVolumeClaim") is None


def test_pdb():
    pdb = _index()[("PodDisruptionBudget", "styx-backend")]
    assert pdb["spec"]["minAvailable"] == 1
    assert pdb["spec"]["selector"]["matchLabels"] == {"app": "styx-backend"}


def test_matrix_notify_external_secret_and_env():
    (es,) = [d for d in _of_kind("ExternalSecret")
             if d["spec"]["target"]["name"] == "styx-matrix-notify"]
    assert es["spec"]["secretStoreRef"] == {"kind": "ClusterSecretStore", "name": "openbao"}
    keys = ["MATRIX_NOTIFY_HOMESERVER", "MATRIX_NOTIFY_ROOM_ID", "MATRIX_NOTIFY_TOKEN"]
    assert [d["secretKey"] for d in es["spec"]["data"]] == keys
    assert {d["remoteRef"]["key"] for d in es["spec"]["data"]} == {"styx/matrix/notify"}
    env = {e["name"]: e for e in _container()["env"]}
    for k in keys:
        ref = env[k]["valueFrom"]["secretKeyRef"]
        assert ref["name"] == "styx-matrix-notify" and ref["key"] == k
