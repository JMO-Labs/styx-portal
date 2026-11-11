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


def check_images(values: dict) -> list[str]:
    refs = images(values)
    errs = [] if len(refs) >= 3 else [f"expected velero, aws plugin and kubectl images, got {refs}"]
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
