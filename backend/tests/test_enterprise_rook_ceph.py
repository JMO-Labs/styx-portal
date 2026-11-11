"""Rook operator values + CephCluster with PVC device sets (issue #27)."""

import importlib.util
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "deploy/enterprise/rook-ceph"
_spec = importlib.util.spec_from_file_location(
    "gen_nvme_pvs", ROOT / "scripts/enterprise/gen_nvme_pvs.py"
)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
HARBOR = "harbor.example.internal"


def _cluster():
    return yaml.safe_load((DIR / "cephcluster.yaml").read_text())


def _spec_():
    return _cluster()["spec"]


def _inv():
    return yaml.safe_load((DIR / "nvme-inventory.yaml").read_text())


def _images(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "image" and isinstance(v, str):
                out.append(v)
            elif k == "image" and isinstance(v, dict):
                out.append(f"{v['repository']}:{v['tag']}")
            else:
                _images(v, out)
    elif isinstance(node, list):
        for v in node:
            _images(v, out)
    return out


def test_kustomization_lists_all_files():
    k = yaml.safe_load((DIR / "kustomization.yaml").read_text())
    assert "cephcluster.yaml" in k["resources"]
    skip = {"kustomization.yaml", "operator-values.yaml", "nvme-inventory.yaml"}
    assert set(k["resources"]) == {p.name for p in DIR.glob("*.yaml")} - skip


def test_generated_cluster_matches_checked_in():
    assert gen.render_cluster(_inv()) == (DIR / "cephcluster.yaml").read_text(), (
        "run scripts/enterprise/gen_nvme_pvs.py"
    )


def test_ceph_image_pinned_not_20_2_0():
    s = _spec_()
    img = s["cephVersion"]["image"]
    assert ":v20.2.5@sha256:" in img and DIGEST.search(img)
    assert "20.2.0" not in img
    assert s["cephVersion"]["allowUnsupported"] is False
    assert img.startswith(HARBOR + "/")


CSI_KEYS = {"cephcsi", "registrar", "provisioner", "snapshotter", "attacher",
            "resizer", "csiAddons"}


def _assert_pinned(d, path):
    assert set(d) == {"repository", "tag"}, (path, sorted(d))
    assert d["repository"].startswith(HARBOR + "/"), path
    assert DIGEST.search(d["tag"]), path


def test_operator_images_digest_pinned():
    vals = yaml.safe_load((DIR / "operator-values.yaml").read_text())
    _assert_pinned(vals["image"], "image")
    assert vals["image"]["repository"].endswith("/rook/ceph")
    assert vals["image"]["tag"].startswith("v1.21.2@")
    assert set(vals["csi"]) == CSI_KEYS
    for k in CSI_KEYS:
        _assert_pinned(vals["csi"][k], f"csi.{k}")
    mgr = vals["ceph-csi-operator"]["controllerManager"]["manager"]
    _assert_pinned(mgr["image"], "ceph-csi-operator.controllerManager.manager.image")
    assert "snapshotMetadata" not in vals["csi"]


def test_no_host_based_osds():
    st = _spec_()["storage"]
    assert st["useAllNodes"] is False and st["useAllDevices"] is False
    assert "nodes" not in st


def test_device_sets_match_inventory():
    sets = _spec_()["storage"]["storageClassDeviceSets"]
    nodes = _inv()["nodes"]
    assert len(sets) == len(nodes)
    for ds, n in zip(sets, nodes, strict=True):
        assert ds["count"] == len(n["nvme"])
        term = ds["placement"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]["nodeSelectorTerms"]
        assert term == [
            {
                "matchExpressions": [
                    {
                        "key": "kubernetes.io/hostname",
                        "operator": "In",
                        "values": [n["hostname"]],
                    }
                ]
            }
        ]
        (vct,) = ds["volumeClaimTemplates"]
        spec = vct["spec"]
        assert spec["volumeMode"] == "Block"
        assert spec["storageClassName"] == "local-nvme"
        assert spec["accessModes"] == ["ReadWriteOnce"]
        assert "encrypted" not in ds


def test_encryption_left_for_20():
    s = _spec_()
    assert "security" not in s or "kms" not in s["security"]
    for ds in s["storage"]["storageClassDeviceSets"]:
        assert "encrypted" not in ds


def test_osd_resources():
    s = _spec_()
    per_node = {len(n["nvme"]) for n in _inv()["nodes"]}
    assert per_node == {2}
    r = s["resources"]["osd"]
    assert r["requests"] == {"cpu": "2", "memory": "8Gi"}
    assert r["limits"] == {"memory": "8Gi"}


def test_priority_classes():
    p = _spec_()["priorityClassNames"]
    assert p["osd"] == "system-node-critical"
    assert p["mon"] == "system-node-critical"
    assert p["mgr"] == "system-cluster-critical"


def test_safety_flags():
    s = _spec_()
    assert s["mon"] == {"count": 3, "allowMultiplePerNode": False}
    assert s["mgr"]["count"] == 2
    assert s["dataDirHostPath"] == "/var/lib/rook"
    assert s["disruptionManagement"]["managePodBudgets"] is True
    assert s["removeOSDsIfOutAndSafeToRemove"] is False


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


def test_mclock_profile_not_in_cephconfig():
    c = _cluster()
    assert not any("mclock_profile" in str(k) for k in _keys(c))
    assert "mclock_profile" not in str(c)
    glob = c["spec"]["cephConfig"]["global"]
    osd = c["spec"]["cephConfig"].get("osd", {})
    merged = {**glob, **osd}
    assert isinstance(merged["osd_scrub_begin_hour"], str)
    assert isinstance(merged["osd_scrub_end_hour"], str)


# --- mClock throttle (issue #29) ---------------------------------------------


def _load(name):
    return yaml.safe_load((DIR / name).read_text())


def test_throttle_cronjob():
    cj = _load("throttle-cronjob.yaml")
    assert cj["kind"] == "CronJob"
    s = cj["spec"]
    assert s["schedule"] == "*/15 * * * *"
    assert s["timeZone"] == "America/New_York"
    assert s["concurrencyPolicy"] == "Forbid"
    pod = s["jobTemplate"]["spec"]["template"]["spec"]
    c = pod["containers"][0]
    assert ":v20.2.5@sha256:4337ac8ac81d40df136e5eac92ca53bb52360a5e039f3d1f7935e729eb5ef42c" in c["image"]
    secrets = {v["secret"]["secretName"] for v in pod["volumes"] if "secret" in v}
    assert secrets == {"rook-ceph-client-throttle"}
    text = (DIR / "throttle-cronjob.yaml").read_text()
    assert "rook-ceph-admin-keyring" not in text
    assert "rook-ceph-mon\n" not in text and "secretName: rook-ceph-mon" not in text
    k = _load("kustomization.yaml")
    gen_ = k["configMapGenerator"][0]
    assert any(f.endswith("throttle/mclock_throttle.py") for f in gen_["files"])
    cm = _load("throttle-config.yaml")
    assert cm["metadata"]["name"] == "ceph-throttle-config"
    assert cm["data"]["window"] == "Mon-Fri 07:00-19:00 America/New_York"
    assert cm["data"]["force"] == ""


def test_throttle_cephclient_least_privilege():
    cc = _load("throttle-cephclient.yaml")
    assert cc["kind"] == "CephClient"
    assert cc["metadata"]["name"] == "throttle"
    caps = cc["spec"]["caps"]
    assert set(caps) == {"mon"}
    assert caps["mon"] == 'allow r, allow command "config set", allow command "config get"'
    assert "allow *" not in caps["mon"]


# --- alerts, runbook, docs (issue #30) ----------------------------------------


def test_prometheus_rules_present():
    pr = _load("prometheusrule.yaml")
    assert pr["kind"] == "PrometheusRule"
    rules = {r["alert"]: r for g in pr["spec"]["groups"] for r in g["rules"]}
    assert rules["CephPGsDegraded"]["for"] == "4h"
    assert "ceph_pg_degraded" in rules["CephPGsDegraded"]["expr"]
    thr = rules["CephThrottleJobFailing"]
    assert "ceph-mclock-throttle" in thr["expr"]
    # staleness only (a failed Job lingers); 3600s + for 5m ~= 1h total
    assert "kube_job_failed" not in thr["expr"]
    assert "> 3600" in thr["expr"] and thr["for"] == "5m"
    assert "prometheusrule.yaml" in _load("kustomization.yaml")["resources"]


def test_rook_ceph_runbook_and_docs():
    docs = ROOT / "docs/enterprise"
    rb = (docs / "runbooks/rook-ceph.md").read_text()
    for needle in ("sgdisk --zap-all", "blkdiscard", "ceph-throttle-config",
                   "harbor.example.internal", "#20", "SC-13", "CM-6", "ADR-0011",
                   "Proposed", "gen_nvme_pvs.py"):
        assert needle in rb, needle
    assert "runbooks/rook-ceph.md" in (ROOT / "zensical.toml").read_text()
    cm = (docs / "control-matrix.md").read_text()
    for cid in ("| SC-5 |", "| CP-2 |"):
        (row,) = [ln for ln in cm.splitlines() if ln.startswith(cid)]
        assert "ADR-0055" in row and "runbooks/rook-ceph.md" in row
    assert "rook-ceph" in (ROOT / "CHANGELOG.md").read_text().split("## 1.0.0")[0]
