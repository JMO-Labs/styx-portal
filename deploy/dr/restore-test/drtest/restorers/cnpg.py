"""CNPG: bootstrap a NEW Cluster from the barman-cloud object store (Guard 4)."""

import json
import os

from .. import checks
from ..guards import Refused, labels

PLUGIN = "barman-cloud.cloudnative-pg.io"
STORE = "styx-drtest-origin"
S3_SECRET = "styx-drtest-cnpg-s3"
ENV = {"ACCESS_KEY_ID": "DRTEST_CNPG_S3_KEY_ID", "ACCESS_SECRET_KEY": "DRTEST_CNPG_S3_SECRET"}


def _meta(cfg, name):
    return {"name": name, "namespace": cfg["namespace"], "labels": labels(cfg["run_id"])}


def require_env():
    missing = [v for v in ENV.values() if not os.environ.get(v)]
    if missing:
        raise Refused(f"set {', '.join(missing)} (read-only S3 key for the CNPG object store)")


def validate(m, server_name):
    """Guard 4: recovery bootstrap, never WAL archiving, never the source name, UTC only."""
    spec = m.get("spec") or {}
    rec = (spec.get("bootstrap") or {}).get("recovery")
    if rec is None:
        raise Refused("CNPG Cluster has no bootstrap.recovery")
    if "plugins" in spec or "backup" in spec:
        raise Refused("CNPG Cluster sets spec.plugins/spec.backup: it would archive WAL "
                      "into the production object store")
    if m["metadata"]["name"] == server_name:
        raise Refused(f"CNPG cluster_name must differ from serverName {server_name}")
    t = (rec.get("recoveryTarget") or {}).get("targetTime")
    if t is not None and not (t.endswith("Z") or t.endswith("+00:00")):
        raise Refused(f"CNPG target_time {t!r} must end in Z or +00:00")


def manifests(cfg):
    """[ObjectStore, Cluster] for the scratch namespace; the Secret is added at apply."""
    c = cfg["cnpg"]
    recovery = {"source": "origin"}
    if c.get("target_time"):
        recovery["recoveryTarget"] = {"targetTime": c["target_time"]}
    o = c["object_store"]
    store = {"apiVersion": "barmancloud.cnpg.io/v1", "kind": "ObjectStore",
             "metadata": _meta(cfg, STORE),
             "spec": {"configuration": {
                 "destinationPath": o["destination_path"], "endpointURL": o["endpoint_url"],
                 "s3Credentials": {
                     "accessKeyId": {"name": S3_SECRET, "key": "ACCESS_KEY_ID"},
                     "secretAccessKey": {"name": S3_SECRET, "key": "ACCESS_SECRET_KEY"}}}}}
    cluster = {"apiVersion": "postgresql.cnpg.io/v1", "kind": "Cluster",
               "metadata": _meta(cfg, c["cluster_name"]),
               "spec": {"instances": 1, "storage": {"size": c.get("storage_size", "20Gi")},
                        "bootstrap": {"recovery": recovery},
                        "externalClusters": [{"name": "origin", "plugin": {
                            "name": PLUGIN, "parameters": {"barmanObjectName": STORE,
                                                           "serverName": c["server_name"]}}}]}}
    validate(cluster, c["server_name"])
    return [store, cluster]


def restore(cfg, runner):
    secret = {"apiVersion": "v1", "kind": "Secret", "metadata": _meta(cfg, S3_SECRET),
              "stringData": {k: os.environ.get(v, f"<{v}>") for k, v in ENV.items()}}
    items = [secret, *manifests(cfg)]
    runner(["kubectl", "apply", "-n", cfg["namespace"], "-f", "-"], step="cnpg-apply",
           write=True, input=json.dumps({"apiVersion": "v1", "kind": "List", "items": items},
                                        indent=2))
    runner(["kubectl", "wait", "--for=condition=Ready", "-n", cfg["namespace"],
            f"clusters.postgresql.cnpg.io/{cfg['cnpg']['cluster_name']}",
            f"--timeout={cfg['cnpg'].get('wait_timeout', '4h')}"], step="cnpg-wait", write=True)


def restored_conn(cfg):
    c = cfg["cnpg"]
    default = {"host": f"{c['cluster_name']}-rw.{cfg['namespace']}.svc", "port": 5432,
               "user": "app", "dbname": "app"}
    return {**default, **(c.get("restored") or {})}


def verify(cfg, runner):
    c = cfg["cnpg"]
    conn = restored_conn(cfg)
    try:
        with open(c["fingerprint"]) as f:
            baseline = json.load(f)["tables"]
    except (OSError, ValueError, KeyError) as e:
        baseline = {}
        runner.sink.err(f"no fingerprint baseline: {e}")
    res = checks.table_checks(checks.fingerprint_tables(runner, conn, c["tables"]), baseline)
    res += [checks.amcheck(runner, conn), checks.alembic(runner, conn, cfg["alembic_head"])]
    return {"source": "cnpg", "backup_id": f"{c['server_name']}@{c.get('target_time') or 'latest'}",
            "recovered_point": checks.replay_point(runner, conn), "checks": res}
