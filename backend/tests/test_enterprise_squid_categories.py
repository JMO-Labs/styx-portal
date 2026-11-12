"""Squid UT1 category updater + CronJob/PVC/mount YAML (issue #166, ADR-0040)."""

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest
import yaml

SQUID = Path(__file__).resolve().parents[2] / "deploy/enterprise/squid"
CATS = SQUID / "categories"
CATEGORIES = ["filehosting", "webmail", "vpn", "redirector", "strong_redirector"]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("update_categories", CATS / "update_categories.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _tarball(path: Path, cat: str, lines: list[str]) -> None:
    data = ("\n".join(lines) + "\n").encode()
    with tarfile.open(path, "w:gz") as tf:
        info = tarfile.TarInfo(f"{cat}/domains")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))


@pytest.fixture
def env(tmp_path):
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    for c in CATEGORIES:
        _tarball(mirror / f"{c}.tar.gz", c, ["b.example.com", "a.example.com", "a.example.com",
                                             "Sub.a.example.com", "10.0.0.1", "# x", ""])
    out = tmp_path / "out"
    out.mkdir()
    return mirror, out


def run(mod, mirror, out):
    return mod.main(["--base-url", mirror.as_uri(), "--out", str(out), "--seed", str(CATS / "seed")])


def test_format_dedupe_sorted_and_paste(mod, env):
    mirror, out = env
    assert run(mod, mirror, out) == 0
    assert (out / "vpn.txt").read_text() == ".a.example.com\n.b.example.com\n"
    assert "\n.pastebin.com\n" in "\n" + (out / "paste.txt").read_text()
    assert not list(out.glob("*.tmp")) and not list(out.glob(".*"))


def test_error_keeps_previous_files(mod, env):
    mirror, out = env
    assert run(mod, mirror, out) == 0
    before = {p.name: p.read_text() for p in out.iterdir()}
    (mirror / "webmail.tar.gz").write_bytes(b"not a tarball")
    _tarball(mirror / "vpn.tar.gz", "vpn", ["changed.example.org"])
    assert run(mod, mirror, out) != 0
    assert {p.name: p.read_text() for p in out.iterdir()} == before
    (mirror / "webmail.tar.gz").unlink()
    assert run(mod, mirror, out) != 0


def test_atomic_replace(mod, tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("old")
    mod.write_atomic(f, ".new.com\n")
    assert f.read_text() == ".new.com\n"
    assert [p.name for p in tmp_path.iterdir()] == ["x.txt"]


def test_seed_copied_only_when_missing(mod, tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    (out / "vpn.txt").write_text(".keep.me\n")
    mod.seed(CATS / "seed", out)
    assert (out / "vpn.txt").read_text() == ".keep.me\n"
    assert (out / "paste.txt").exists() and (out / "webmail.txt").exists()


def test_seed_lists_valid():
    for c in [*CATEGORIES, "paste"]:
        lines = (CATS / "seed" / f"{c}.txt").read_text().split()
        assert lines and all(x.startswith(".") for x in lines), c
    assert ".pastebin.com" in (CATS / "seed/paste.txt").read_text().split()


def docs(name):
    return list(yaml.safe_load_all((SQUID / name).read_text()))


def test_cronjob_pvc_and_policy():
    items = docs("categories-cronjob.yaml")
    kinds = {d["kind"]: d for d in items}
    pvc = kinds["PersistentVolumeClaim"]
    assert pvc["metadata"]["name"] == "squid-categories"
    assert pvc["spec"]["accessModes"] == ["ReadWriteMany"]
    cj = kinds["CronJob"]
    assert len(cj["spec"]["schedule"].split()) == 5 and cj["spec"]["schedule"].endswith("* * *")
    pod = cj["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert any(v.get("persistentVolumeClaim", {}).get("claimName") == "squid-categories"
               for v in pod["volumes"])
    cm = kinds["ConfigMap"]
    assert "https://dsi.ut-capitole.fr/blacklists/download" in cm["data"]["UT1_BASE_URL"]
    cnp = kinds["CiliumNetworkPolicy"]
    sel = cnp["spec"]["endpointSelector"]["matchLabels"]
    labels = cj["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"]
    assert sel.items() <= labels.items()
    ports = [p["port"] for r in cnp["spec"]["egress"] for tp in r.get("toPorts", [])
             for p in tp["ports"]]
    assert sorted(ports) == ["443", "53"]


def test_squid_mounts_pvc_readonly_with_reload_sidecar():
    dep = docs("deployment.yaml")[0]
    spec = dep["spec"]["template"]["spec"]
    vol = next(v for v in spec["volumes"] if v["name"] == "categories")
    assert vol == {"name": "categories",
                   "persistentVolumeClaim": {"claimName": "squid-categories", "readOnly": True}}
    mounts = [m for c in spec["containers"] for m in c["volumeMounts"] if m["name"] == "categories"]
    assert mounts and all(m["mountPath"] == "/etc/squid/categories" and m["readOnly"] for m in mounts)
    side = next(c for c in spec["containers"] if c["name"] != "squid")
    assert "squid -k reconfigure" in " ".join(side["args"]) and "3600" in " ".join(side["args"])


def test_kustomization_lists_new_resources():
    res = yaml.safe_load((SQUID / "kustomization.yaml").read_text())["resources"]
    assert "categories-cronjob.yaml" in res
    assert "categories-script.yaml" in res or any("categories" in r for r in res)
