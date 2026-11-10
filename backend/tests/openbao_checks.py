"""Pure validators for the OpenBao / External Secrets IaC (issue #4).

Each check takes parsed data and returns a list of human-readable errors (empty = ok),
so the positive tests run them on the real files and the negative tests on bad fixtures.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OPENBAO = ROOT / "deploy/enterprise/openbao"
ESO = ROOT / "deploy/enterprise/external-secrets"
HARBOR = "harbor.example.internal/"
CEPH = re.compile(r"ceph|rook", re.I)
SEAL_DIR = "/etc/openbao/seal"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def load_docs(path: Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def strip_comments(hcl: str) -> str:
    return "\n".join(ln for ln in hcl.splitlines() if not ln.lstrip().startswith(("#", "//")))


# ---- images -----------------------------------------------------------------------


def images(node) -> list[str]:
    """Every image reference: Helm-style {registry, repository, tag} dicts and plain strings."""
    found: list[str] = []
    if isinstance(node, dict):
        if "repository" in node and "tag" in node:
            reg = node.get("registry")
            repo = f"{reg}/{node['repository']}" if reg else node["repository"]
            found.append(f"{repo}:{node['tag']}")
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
    imgs = images(values)
    if not imgs:
        return ["no images found"]
    return [f"image not pinned by digest under {HARBOR}: {i}" for i in imgs
            if "@sha256:" not in i or not i.startswith(HARBOR)]


# ---- OpenBao server values ------------------------------------------------------------


def check_ha(values: dict) -> list[str]:
    s, errs = values["server"], []
    ha = s.get("ha", {})
    if ha.get("enabled") is not True:
        errs.append("server.ha.enabled must be true")
    if ha.get("replicas") != 3:
        errs.append(f"server.ha.replicas must be 3, got {ha.get('replicas')}")
    if ha.get("raft", {}).get("enabled") is not True:
        errs.append("server.ha.raft.enabled must be true")
    if s.get("authDelegator", {}).get("enabled") is not True:
        errs.append("server.authDelegator.enabled must be true")
    for k in ("injector", "ui"):
        if values.get(k, {}).get("enabled") is not False:
            errs.append(f"{k}.enabled must be false")
    return errs


def check_scheduling(values: dict) -> list[str]:
    s, errs = values["server"], []
    if s.get("nodeSelector") != {"node-role.kubernetes.io/control-plane": "true"}:
        errs.append("nodeSelector must be node-role.kubernetes.io/control-plane: 'true'")
    tols = {(t.get("key"), t.get("effect")) for t in s.get("tolerations") or []}
    for want in (("node-role.kubernetes.io/control-plane", "NoSchedule"),
                 ("CriticalAddonsOnly", "NoExecute")):
        if want not in tols:
            errs.append(f"missing toleration {want}")
    aff = s.get("affinity")
    aff = yaml.safe_load(aff) if isinstance(aff, str) else aff or {}
    req = aff.get("podAntiAffinity", {}).get("requiredDuringSchedulingIgnoredDuringExecution", [])
    if not any(r.get("topologyKey") == "kubernetes.io/hostname" for r in req):
        errs.append("required pod anti-affinity on kubernetes.io/hostname missing")
    return errs


def check_storage(values: dict) -> list[str]:
    sc = values["server"].get("dataStorage", {}).get("storageClass")
    if sc != "openbao-local":
        return [f"raft dataStorage.storageClass must be openbao-local (never Ceph), got {sc}"]
    return []


def ceph_storage_refs(node) -> list[str]:
    """storageClass/storageClassName values that name Ceph or Rook."""
    hits: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("storageClass", "storageClassName") and isinstance(v, str) and CEPH.search(v):
                hits.append(v)
            hits += ceph_storage_refs(v)
    elif isinstance(node, list):
        for v in node:
            hits += ceph_storage_refs(v)
    return hits


def check_raft_hcl(hcl: str) -> list[str]:
    code, errs = strip_comments(hcl), []
    seals = re.findall(r'^\s*seal\s+"([^"]+)"', code, re.M)
    if seals != ["static"]:
        errs.append(f"need exactly one seal \"static\", got {seals}")
    kid = re.search(r'^\s*current_key_id\s*=\s*"([^"]+)"', code, re.M)
    key = re.search(r'^\s*current_key\s*=\s*"([^"]+)"', code, re.M)
    if not kid or not key:
        errs.append("static seal needs current_key_id and current_key")
    elif not (key.group(1).startswith("file:///openbao/seal/")
              and key.group(1).endswith(f"/{kid.group(1)}.key")):
        errs.append(f"current_key must be file:///openbao/seal/<current_key_id>.key, got {key.group(1)}")
    if "env://" in code:
        errs.append("seal key must not come from env://")
    if not re.search(r'^\s*tls_cert_file\s*=\s*"/openbao/tls/', code, re.M):
        errs.append("listener needs tls_cert_file under /openbao/tls")
    if re.search(r'tls_disable\s*=\s*"?(true|1)', code):
        errs.append("TLS must not be disabled (tls_disable)")
    if "tls_skip_verify" in code:
        errs.append("tls_skip_verify is forbidden")
    if re.search(r"disable_mlock\s*=\s*false", code):
        errs.append("disable_mlock = false conflicts with the chart")
    joins = re.findall(r"retry_join\s*\{(.*?)\}", code, re.S)
    if len(joins) != 3 or not all("leader_ca_cert_file" in j for j in joins):
        errs.append("storage raft needs 3 retry_join blocks with leader_ca_cert_file")
    return errs


def check_volumes(values: dict) -> list[str]:
    s, errs = values["server"], []
    vols = s.get("volumes") or []
    host = [v for v in vols if "hostPath" in v]
    if len(host) != 1 or host[0]["hostPath"].get("path") != SEAL_DIR:
        return [f"exactly one hostPath volume ({SEAL_DIR}) allowed, got {[v['name'] for v in host]}"]
    if host[0]["hostPath"].get("type") != "Directory":
        errs.append("seal hostPath type must be Directory")
    mounts = [m for m in s.get("volumeMounts") or [] if m.get("name") == host[0]["name"]]
    if not mounts or any(m.get("readOnly") is not True or m.get("mountPath") != "/openbao/seal"
                         for m in mounts):
        errs.append("seal hostPath must be mounted readOnly: true at /openbao/seal")
    return errs


def check_security_context(pod: dict, container: dict) -> list[str]:
    errs = []
    if not (pod.get("runAsNonRoot") or container.get("runAsNonRoot")):
        errs.append("runAsNonRoot must be true")
    if container.get("allowPrivilegeEscalation") is not False:
        errs.append("allowPrivilegeEscalation must be false")
    if container.get("capabilities", {}).get("drop") != ["ALL"]:
        errs.append("capabilities.drop must be [ALL]")
    seccomp = container.get("seccompProfile") or pod.get("seccompProfile") or {}
    if seccomp.get("type") != "RuntimeDefault":
        errs.append("seccompProfile must be RuntimeDefault")
    return errs


def check_values(values: dict) -> list[str]:
    sc = values["server"].get("statefulSet", {}).get("securityContext", {})
    return (check_ha(values) + check_images(values) + check_scheduling(values)
            + check_storage(values) + check_raft_hcl(values["server"]["ha"]["raft"]["config"])
            + check_volumes(values)
            + check_security_context(sc.get("pod") or {}, sc.get("container") or {}))


# ---- policies -------------------------------------------------------------------------

PATH_RULE = re.compile(r'path\s+"([^"]+)"\s*\{\s*capabilities\s*=\s*\[([^\]]*)\]\s*\}', re.S)


def policy_paths(hcl: str) -> dict[str, set[str]]:
    code = strip_comments(hcl)
    rules = PATH_RULE.findall(code)
    if len(rules) != len(re.findall(r"\bpath\s+\"", code)):
        raise ValueError("policy has a path block the checker cannot parse")
    return {p: set(re.findall(r'"([^"]+)"', caps)) for p, caps in rules}


def check_policy(hcl: str) -> list[str]:
    errs = []
    for path, caps in policy_paths(hcl).items():
        if path in ("*", "sys/*", "+/*"):
            errs.append(f"wildcard root path {path!r} is forbidden")
        if caps & {"sudo", "root"}:
            errs.append(f"{path}: sudo/root capability is forbidden")
    return errs


# ---- committed key material -----------------------------------------------------------

PRIVATE_KEY = re.compile(r"BEGIN .*PRIVATE KEY")
SECRET_KIND = re.compile(r"^kind:\s*Secret\s*$", re.M)
SECRET_DATA = re.compile(r"^\s*(data|stringData):", re.M)
KEY_VALUE = re.compile(r"key\w*[\"']?\s*[:=]\s*[\"']?([0-9a-fA-F]{64}|[A-Za-z0-9+/]{43}=)(?![\w+/=])",
                       re.I)


def leaks(text: str) -> list[str]:
    errs = []
    if PRIVATE_KEY.search(text):
        errs.append("private key block")
    for doc in re.split(r"^---\s*$", text, flags=re.M):
        if SECRET_KIND.search(doc) and SECRET_DATA.search(doc):
            errs.append("kind: Secret with data/stringData")
    if KEY_VALUE.search(text):
        errs.append("64-hex or 44-char base64 value next to a key")
    return errs
