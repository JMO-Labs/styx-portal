"""Pure validators for the Velero backup IaC (deploy/enterprise/backup).

Each check takes parsed data and returns a list of human-readable errors (empty = ok).
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "deploy/enterprise/backup"
HARBOR = "harbor.example.internal/"
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def load_docs(path: Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def images(node) -> list[str]:
    """Image refs: {repository, tag?, digest?} dicts, plain `image:` strings, and list items."""
    found: list[str] = []
    if isinstance(node, dict):
        if "repository" in node and ("tag" in node or "digest" in node):
            ref = node["repository"]
            ref += f":{node['tag']}" if node.get("tag") else ""
            ref += f"@{node['digest']}" if node.get("digest") else ""
            found.append(ref)
        for k, v in node.items():
            if k == "image" and isinstance(v, str):
                found.append(v)
            else:
                found += images(v)
    elif isinstance(node, list):
        for v in node:
            found += images(v)
    return found


def check_images(values: dict, minimum: int = 3) -> list[str]:
    refs = images(values)
    errs = [] if len(refs) >= minimum else [f"expected at least {minimum} images, got {refs}"]
    for ref in refs:
        if not ref.startswith(HARBOR):
            errs.append(f"image not from {HARBOR}: {ref}")
        if not DIGEST.search(ref):
            errs.append(f"image not pinned by @sha256 digest: {ref}")
    return errs


def check_bsl(values: dict) -> list[str]:
    cfg = values.get("configuration", {})
    bsls = cfg.get("backupStorageLocation", [])
    errs = []
    if [b.get("name") for b in bsls] != ["offsite"]:
        errs.append(f"exactly one BSL named offsite required, got {[b.get('name') for b in bsls]}")
    for b in bsls:
        if b.get("provider") != "aws":
            errs.append("BSL provider must be aws (S3)")
        if not b.get("bucket"):
            errs.append("BSL bucket missing")
        if not str(b.get("prefix", "")).startswith("velero"):
            errs.append("BSL prefix must start with velero")
    if values.get("deployNodeAgent") is not False:
        errs.append("deployNodeAgent must be false")
    if cfg.get("defaultVolumesToFsBackup"):
        errs.append("defaultVolumesToFsBackup must be false/absent")
    if not values.get("metrics", {}).get("enabled"):
        errs.append("metrics.enabled must be true")
    if values.get("metrics", {}).get("serviceMonitor", {}).get("enabled") is not True:
        errs.append("metrics.serviceMonitor.enabled must be true")
    return errs


def check_externalsecrets(docs: list[dict], text: str = "") -> list[str]:
    errs = []
    for d in docs:
        if d.get("kind") == "Secret":
            errs.append("kind: Secret is not allowed, use ExternalSecret")
        if d.get("kind") == "ExternalSecret":
            if d["spec"]["secretStoreRef"] != {"kind": "ClusterSecretStore", "name": "openbao"}:
                errs.append(f"{d['metadata']['name']}: must use ClusterSecretStore openbao")
            if "value" in str(d["spec"].get("data", "")).replace("remoteRef", ""):
                errs.append(f"{d['metadata']['name']}: literal value in data")
    names = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "ExternalSecret"}
    repo = names.get("velero-repo-credentials")
    if not repo:
        errs.append("ExternalSecret velero-repo-credentials missing")
    else:
        if repo["spec"]["target"]["name"] != "velero-repo-credentials":
            errs.append("velero-repo-credentials target name wrong")
        if "repository-password" not in {x["secretKey"] for x in repo["spec"]["data"]}:
            errs.append("velero-repo-credentials needs key repository-password")
    if len(names) < 2:
        errs.append("need BSL credentials and repo-credentials ExternalSecrets")
    return errs


# ---- home snapshots (issue #38) ---------------------------------------------------------

NIGHTLY = re.compile(r"^nightly-\d{4}-\d{2}-\d{2}$")
ADMIN = re.compile(r"rook-ceph-admin|client\.admin|ceph-admin")


def check_snapshot_name(name: str) -> list[str]:
    return [] if NIGHTLY.match(name) else [f"snapshot name must match nightly-YYYY-MM-DD: {name}"]


def check_no_ceph_admin(text: str) -> list[str]:
    return [f"ceph admin credentials referenced: {m}" for m in sorted(set(ADMIN.findall(text)))]


def check_cronjob(cj: dict) -> list[str]:
    errs = check_no_ceph_admin(yaml.safe_dump(cj))
    spec = cj["spec"]
    if spec.get("concurrencyPolicy") != "Forbid":
        errs.append("concurrencyPolicy must be Forbid")
    if spec.get("timeZone") != "Etc/UTC":
        errs.append("timeZone must be Etc/UTC")
    deadline = spec["jobTemplate"]["spec"].get("activeDeadlineSeconds", 0)
    if not 0 < deadline <= 4800:
        errs.append("activeDeadlineSeconds must be in (0, 4800]")
    pod = spec["jobTemplate"]["spec"]["template"]["spec"]
    for c in pod["containers"]:
        sc = c.get("securityContext", {})
        if not sc.get("readOnlyRootFilesystem"):
            errs.append("readOnlyRootFilesystem must be true")
        if sc.get("privileged"):
            errs.append("privileged must be false")
        if sc.get("capabilities", {}).get("drop") != ["ALL"]:
            errs.append("capabilities.drop must be [ALL]")
        if not (pod.get("securityContext", {}).get("runAsNonRoot") or sc.get("runAsNonRoot")):
            errs.append("runAsNonRoot must be true")
        errs += check_images({"image": c["image"]}, minimum=1)
    return errs


EXCLUDED_NS = {"rook-ceph", "openbao", "kube-system", "velero", "styx-backup"}
CNPG = "clusters.postgresql.cnpg.io"


def check_schedules(docs: list[dict]) -> list[str]:
    errs = []
    names = {d["metadata"]["name"] for d in docs}
    if names != {"daily", "weekly"}:
        errs.append(f"schedules must be daily and weekly, got {sorted(names)}")
    for d in docs:
        n, t = d["metadata"]["name"], d["spec"].get("template", {})
        if t.get("storageLocation") != "offsite":
            errs.append(f"{n}: storageLocation must be offsite")
        if t.get("snapshotMoveData") is not True:
            errs.append(f"{n}: snapshotMoveData must be true")
        if t.get("defaultVolumesToFsBackup"):
            errs.append(f"{n}: defaultVolumesToFsBackup must not be true")
        if missing := EXCLUDED_NS - set(t.get("excludedNamespaces", [])):
            errs.append(f"{n}: excludedNamespaces missing {sorted(missing)}")
        if CNPG not in t.get("excludedResources", []):
            errs.append(f"{n}: excludedResources missing {CNPG}")
    return errs
RULE_FILE = Path(__file__).resolve().parents[2] / "deploy/enterprise/backup/prometheusrule.yaml"
STALE_SECONDS = "93600"  # 26 h


def load_rule(path: Path = RULE_FILE) -> dict:
    return yaml.safe_load(path.read_text())


def alerts(rule: dict) -> dict:
    return {r["alert"]: r for g in rule["spec"]["groups"] for r in g["rules"] if "alert" in r}


def check_stale(name: str, alert: dict) -> None:
    expr = alert["expr"]
    if STALE_SECONDS not in expr:
        raise ValueError(f"{name}: stale expr lacks {STALE_SECONDS}")
    if "absent(" not in expr:
        raise ValueError(f"{name}: stale expr lacks absent(")


def check_stale_alerts(rule: dict) -> None:
    for name, a in alerts(rule).items():
        if name.endswith("Stale"):
            check_stale(name, a)


BACKUP_DIR = RULE_FILE.parent
FORBIDDEN_KINDS = {"ObjectStore", "ScheduledBackup", "Cluster"}  # owned by the CNPG overlay (#24)


def check_backup_dir(path: Path = BACKUP_DIR) -> None:
    for f in sorted(path.rglob("*.y*ml")):
        for doc in yaml.safe_load_all(f.read_text()):
            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind")
            if kind in FORBIDDEN_KINDS:
                raise ValueError(f"{f.relative_to(path)}: {kind} belongs in the CNPG overlay, not backup/")
            if kind == "Secret" and "stringData" in doc:
                raise ValueError(f"{f.relative_to(path)}: plain Secret with stringData is not allowed")
