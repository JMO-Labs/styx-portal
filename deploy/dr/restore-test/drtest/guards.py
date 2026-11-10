"""Hard guards: refuse any target not proven scratch, before the first write (issue #15).

Every function here only reads (kubectl/velero get) or inspects local paths and config.
"""

import json
import os
import re

RUN_LABEL = "styx.io/dr-run"
SCRATCH_LABEL = "styx.io/dr-scratch"
NS_RE = re.compile(r"styx-drtest-[a-z0-9]([a-z0-9-]*[a-z0-9])?")
DNS_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
DENY = {"styx", "default", "velero", "openbao", "rook-ceph", "styx-backup"}
DENY_PREFIX = ("kube-", "cnpg-")


class Refused(Exception):
    """A guard refused the target. The CLI exits 2 and nothing has been written."""


def labels(run_id):
    return {SCRATCH_LABEL: "true", RUN_LABEL: run_id}


def namespace_manifest(ns, run_id):
    return {"apiVersion": "v1", "kind": "Namespace",
            "metadata": {"name": ns, "labels": labels(run_id)}}


def namespace_name(ns):
    """Guard 2 (name part): scratch pattern only, deny-list always refused."""
    if not isinstance(ns, str) or ns in DENY or ns.startswith(DENY_PREFIX) \
            or not NS_RE.fullmatch(ns) or len(ns) > 63:
        raise Refused(f"namespace {ns!r} is not a scratch namespace (^styx-drtest-[a-z0-9-]+$)")


def _json(p, what):
    try:
        return json.loads(p.stdout or "")
    except ValueError:
        raise Refused(f"cannot parse {what}") from None


def cluster(cfg, runner):
    """Guard 1: identify the cluster by kube-system UID (context names can be renamed)."""
    p = runner(["kubectl", "get", "namespace", "kube-system", "-o", "jsonpath={.metadata.uid}"],
               step="guard-cluster")
    uid = p.stdout.strip()
    if p.returncode or not uid:
        raise Refused("cannot read the kube-system namespace UID")
    if uid in cfg["prod_cluster_uids"]:
        raise Refused(f"cluster {uid} is listed in prod_cluster_uids (production)")
    if cfg["mode"] == "full-site" and uid not in cfg["scratch_cluster_uids"]:
        raise Refused(f"full-site mode needs a cluster in scratch_cluster_uids, got {uid}")
    return uid


def namespace(ns, run_id, runner):
    """Guard 2: True if ns exists and carries this run's labels; False if absent.

    An unreadable namespace counts as absent: it is then created with `kubectl create`,
    which fails rather than adopting a namespace that already exists.
    """
    namespace_name(ns)
    p = runner(["kubectl", "get", "namespace", ns, "-o", "json"], step="guard-namespace")
    if p.returncode:
        return False
    have = (_json(p, f"namespace {ns}").get("metadata") or {}).get("labels") or {}
    if any(have.get(k) != v for k, v in labels(run_id).items()):
        raise Refused(f"namespace {ns} exists without the label {RUN_LABEL}={run_id}")
    return True


def velero_targets(cfg):
    """Guard 3 (config part): every included namespace is mapped to a scratch namespace."""
    v = cfg["velero"]
    inc, maps = v["include_namespaces"], v["namespace_mappings"]
    # Literal names only: Velero expands globs (*?[]) but mappings match literally,
    # so an unmapped match would be restored in place.
    if not inc or not all(isinstance(n, str) and DNS_LABEL.fullmatch(n) for n in inc):
        raise Refused("velero include_namespaces must be literal namespace names "
                      "(no globs, no commas)")
    missing = [n for n in inc if n not in maps]
    if missing:
        raise Refused(f"velero namespace_mappings miss {', '.join(missing)} "
                      "(Velero restores unmapped namespaces in place)")
    for n in inc:
        namespace_name(maps[n])
    return [maps[n] for n in inc]


def velero_bsl(cfg, runner):
    """Guard 3 (cluster part): the backup's BSL is not production and is ReadOnly."""
    v = cfg["velero"]
    vns = v.get("namespace", "velero")
    p = runner(["velero", "backup", "get", v["backup"], "-n", vns, "-o", "json"],
               step="guard-velero-backup")
    if p.returncode:
        raise Refused(f"cannot read velero backup {v['backup']}")
    b = _json(p, "velero backup")
    b = (b.get("items") or [b])[0]
    bsl = (b.get("spec") or {}).get("storageLocation")
    if not bsl or bsl == v["prod_bsl"]:
        raise Refused(f"velero backup uses BSL {bsl!r}, the production BSL; "
                      "use a separate ReadOnly BSL on the same bucket")
    p = runner(["kubectl", "get", "backupstoragelocations.velero.io", bsl, "-n", vns,
                "-o", "json"], step="guard-velero-bsl")
    mode = (_json(p, "BSL").get("spec") or {}).get("accessMode") if not p.returncode else None
    if mode != "ReadOnly":
        raise Refused(f"velero BSL {bsl} accessMode is {mode!r}, must be ReadOnly")


def kopia_targets(cfg):
    """Guard 5: restore targets resolve (realpath) strictly inside scratch_mount_root."""
    k = cfg["kopia"]
    root = os.path.realpath(k["scratch_mount_root"])
    if root == "/":
        raise Refused("kopia scratch_mount_root must not be /")
    for s in k["sources"]:
        t = os.path.realpath(s["target"])
        if t == root or os.path.commonpath([root, t]) != root:
            raise Refused(f"kopia target {s['target']} resolves outside {root}")
