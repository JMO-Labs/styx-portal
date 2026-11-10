"""Restorer command and manifest builders (issue #15)."""

import pytest

from drtest.guards import Refused
from drtest.restorers import cnpg, kopia, velero

from .conftest import NS, base_cfg, full_run_setup


def cluster(cfg):
    return next(m for m in cnpg.manifests(cfg) if m["kind"] == "Cluster")


def test_cnpg_manifest_has_no_plugins_or_backup(tmp_path):
    m = cluster(base_cfg(tmp_path))
    assert "recovery" in m["spec"]["bootstrap"]
    assert "plugins" not in m["spec"] and "backup" not in m["spec"]
    assert m["metadata"]["namespace"] == NS
    for bad in ("plugins", "backup"):
        with pytest.raises(Refused):
            cnpg.validate({**m, "spec": {**m["spec"], bad: [{}]}}, "styx-db")


def test_cnpg_name_differs_from_server_name(tmp_path):
    cfg = base_cfg(tmp_path)
    cfg["cnpg"]["cluster_name"] = cfg["cnpg"]["server_name"]
    with pytest.raises(Refused):
        cnpg.manifests(cfg)


@pytest.mark.parametrize("t,ok", [
    ("2026-11-09T03:00:00", False), ("2026-11-09T03:00:00+02:00", False),
    ("2026-11-09T03:00:00Z", True), ("2026-11-09 03:00:00+00:00", True)])
def test_cnpg_target_time_requires_utc(tmp_path, t, ok):
    cfg = base_cfg(tmp_path)
    cfg["cnpg"]["target_time"] = t
    if ok:
        rec = cluster(cfg)["spec"]["bootstrap"]["recovery"]
        assert rec["recoveryTarget"]["targetTime"] == t
    else:
        with pytest.raises(Refused):
            cnpg.manifests(cfg)


def test_velero_command_flags(tmp_path):
    cfg = base_cfg(tmp_path)
    cfg["velero"]["include_namespaces"] = ["styx", "keycloak"]
    cfg["velero"]["namespace_mappings"] = {"styx": NS, "keycloak": "styx-drtest-t1-kc"}
    argv = velero.restore_argv(cfg)
    assert argv[:3] == ["velero", "restore", "create"]
    assert "--include-cluster-resources=false" in argv
    i = argv.index("--namespace-mappings")
    assert argv[i + 1] == f"styx:{NS},keycloak:styx-drtest-t1-kc"
    assert argv[argv.index("--include-namespaces") + 1] == "styx,keycloak"


def test_kopia_connect_is_readonly(tmp_path):
    assert "--readonly" in kopia.connect_argv(base_cfg(tmp_path), tmp_path / "k.cfg")


def test_kopia_connect_is_readonly_in_full_run(h, health):
    full_run_setup(h, health)
    r = h.cli("run", "--confirm", "t1")
    assert r.returncode == 0, r.stdout + r.stderr
    connects = [c for c in h.calls() if c[0] == "kopia" and "connect" in c]
    assert connects and all("--readonly" in c for c in connects)
