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
