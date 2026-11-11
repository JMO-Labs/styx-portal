"""Rook-Ceph local NVMe PV generator: output, drift and safety guards (issue #26)."""

import copy
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "deploy/enterprise/rook-ceph"
_spec = importlib.util.spec_from_file_location(
    "gen_nvme_pvs", ROOT / "scripts/enterprise/gen_nvme_pvs.py"
)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

PFX = "/dev/disk/by-id/nvme-"


def _inv():
    return yaml.safe_load((DIR / "nvme-inventory.yaml").read_text())


def _pvs(inv=None):
    return list(yaml.safe_load_all(gen.render(inv or _inv())))


def test_generated_pvs_match_checked_in():
    assert gen.render(_inv()) == (DIR / "local-pvs.yaml").read_text(), (
        "run scripts/enterprise/gen_nvme_pvs.py"
    )


def test_inventory_shape():
    nodes = _inv()["nodes"]
    assert [n["hostname"] for n in nodes] == [f"worker-0{i}" for i in range(1, 9)]
    assert all(len(n["nvme"]) == 2 and n["os_disk"] for n in nodes)


def test_every_pv_block_local_by_id():
    pvs = _pvs()
    assert len(pvs) == 16
    for pv in pvs:
        spec = pv["spec"]
        assert spec["volumeMode"] == "Block"
        assert spec["storageClassName"] == "local-nvme"
        assert spec["persistentVolumeReclaimPolicy"] == "Retain"
        assert spec["local"]["path"].startswith(PFX)
        terms = spec["nodeAffinity"]["required"]["nodeSelectorTerms"]
        assert len(terms) == 1
        expr = terms[0]["matchExpressions"]
        assert len(expr) == 1 and expr[0]["key"] == "kubernetes.io/hostname"
        assert len(expr[0]["values"]) == 1


def test_kustomization_lists_manifests():
    k = yaml.safe_load((DIR / "kustomization.yaml").read_text())
    skip = {"kustomization.yaml", "operator-values.yaml", "nvme-inventory.yaml"}
    assert set(k["resources"]) == {p.name for p in DIR.glob("*.yaml")} - skip


def _bad(mutate):
    inv = copy.deepcopy(_inv())
    mutate(inv)
    return inv


def test_rejects_kernel_name_path():
    inv = _bad(lambda i: i["nodes"][0]["nvme"][0].update(path="/dev/nvme0n1"))
    with pytest.raises(gen.InventoryError, match="by-id"):
        gen.render(inv)


@pytest.mark.parametrize(
    "bad",
    [
        PFX + "x/../../../nvme0n1",
        "/dev/disk/by-id/nvme-x/../../../sda",
        PFX + "a/b",
        PFX,
    ],
)
def test_rejects_traversal_path(bad):
    inv = _bad(lambda i: i["nodes"][0]["nvme"][0].update(path=bad))
    with pytest.raises(gen.InventoryError, match="by-id"):
        gen.render(inv)


def test_rejects_missing_keys():
    inv = _bad(lambda i: i["nodes"][0]["nvme"][0].pop("size"))
    with pytest.raises(gen.InventoryError, match="size"):
        gen.render(inv)


def test_rejects_other_nodes_os_disk():
    def m(i):
        i["nodes"][0]["nvme"][0]["path"] = i["nodes"][1]["os_disk"]

    with pytest.raises(gen.InventoryError, match="os_disk"):
        gen.render(_bad(m))


def test_rejects_os_disk():
    def m(i):
        n = i["nodes"][0]
        n["nvme"][0]["path"] = n["os_disk"]

    with pytest.raises(gen.InventoryError, match="os_disk"):
        gen.render(_bad(m))


def test_rejects_duplicate_path():
    def m(i):
        i["nodes"][1]["nvme"][0]["path"] = i["nodes"][0]["nvme"][0]["path"]

    with pytest.raises(gen.InventoryError, match="duplicate"):
        gen.render(_bad(m))


def test_rejects_node_without_nvme():
    with pytest.raises(gen.InventoryError, match="no NVMe"):
        gen.render(_bad(lambda i: i["nodes"][2].update(nvme=[])))


def test_pv_names_unique_and_stable():
    names = [p["metadata"]["name"] for p in _pvs()]
    assert len(set(names)) == len(names)
    assert names == [p["metadata"]["name"] for p in _pvs()]
    inv = _inv()
    inv["nodes"][0]["nvme"].reverse()
    assert set(p["metadata"]["name"] for p in _pvs(inv)) == set(names)
    assert names[0].startswith("local-nvme-worker-01-")


def test_cli_exit_nonzero_on_bad_input(tmp_path, capsys):
    inv = _bad(lambda i: i["nodes"][0]["nvme"][0].update(path="/dev/nvme0n1"))
    f = tmp_path / "inv.yaml"
    f.write_text(yaml.safe_dump(inv))
    assert gen.main(["--inventory", str(f), "--output", str(tmp_path / "o.yaml")]) == 1
    assert "by-id" in capsys.readouterr().err
    assert not (tmp_path / "o.yaml").exists()


def test_device_set_count_follows_nvme_count():
    inv = _inv()
    inv["nodes"][0]["nvme"].append({"path": PFX + "EXTRA_SN010003", "size": "3840Gi"})
    sets = yaml.safe_load(gen.render_cluster(inv))["spec"]["storage"]["storageClassDeviceSets"]
    assert sets[0]["count"] == 3 and sets[1]["count"] == 2
    assert sets[0]["name"] == "worker-01"
