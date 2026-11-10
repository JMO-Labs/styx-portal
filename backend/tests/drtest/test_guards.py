"""Hard guards refuse non-scratch targets before the first write (issue #15)."""

import json
import os

import pytest

from .conftest import NS, RUN, UID, full_run_setup


def refused(h):
    r = h.cli("run", "--confirm", RUN)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "REFUSED" in r.stderr
    assert h.writes() == []
    assert h.only_reads()
    assert not (h.tmp / "evidence").exists()
    return r


def test_refuses_prod_cluster_uid(h):
    h.cfg["prod_cluster_uids"] = [UID]
    assert "production" in refused(h).stderr


def test_refuses_unreadable_cluster_uid(h):
    h.on(r"^kubectl get namespace kube-system", code=1)
    refused(h)


def test_full_site_requires_scratch_uid(h):
    h.cfg["mode"] = "full-site"
    refused(h)
    h.cfg["scratch_cluster_uids"] = [UID]
    assert h.cli("plan").returncode == 0


DENY = ["styx", "default", "kube-system", "kube-public", "cnpg-system", "velero", "openbao",
        "rook-ceph", "styx-backup", "STYX-DRTEST-x", "styx-drtest-", "styx-drtest-a;rm",
        "styx-drtest-a\n", "styx-drtest-../x"]


@pytest.mark.parametrize("ns", DENY)
def test_refuses_namespace_styx(h, ns):
    h.cfg["namespace"] = ns
    h.cfg["velero"]["namespace_mappings"] = {"styx": ns}
    refused(h)


@pytest.mark.parametrize("ns", DENY)
def test_refuses_velero_mapping_target(h, ns):
    h.cfg["velero"]["namespace_mappings"] = {"styx": ns}
    refused(h)


def test_refuses_existing_namespace_without_run_label(h):
    h.on(rf"^kubectl get namespace {NS}",
         out='{"metadata":{"labels":{"styx.io/dr-run":"other","styx.io/dr-scratch":"true"}}}')
    refused(h)


def test_accepts_existing_namespace_with_own_run_label(h):
    h.on(rf"^kubectl get namespace {NS}",
         out='{"metadata":{"labels":{"styx.io/dr-run":"t1","styx.io/dr-scratch":"true"}}}')
    r = h.cli("plan")
    assert r.returncode == 0, r.stderr
    assert "kubectl create" not in r.stdout  # namespace already ours, not re-created


def test_velero_mapping_must_cover_all_namespaces(h):
    h.cfg["velero"]["include_namespaces"] = ["styx", "keycloak"]
    assert "keycloak" in refused(h).stderr


@pytest.mark.parametrize("inc", [[], ["*"], [""], ["styx*"], ["sty?"], ["[s]tyx"], ["s*"],
                                 ["Styx"], ["styx-"]])
def test_velero_refuses_empty_or_wildcard_include(h, inc):
    # Velero expands globs but mappings match literal names: unmapped matches
    # would be restored in place into production.
    h.cfg["velero"]["include_namespaces"] = inc
    h.cfg["velero"]["namespace_mappings"] = {n: NS for n in inc}
    refused(h)


def test_velero_refuses_readwrite_bsl(h):
    h.on(r"^kubectl get backupstoragelocations", out='{"spec":{"accessMode":"ReadWrite"}}')
    refused(h)


def test_velero_refuses_prod_bsl_name(h):
    h.on(r"^velero backup get", out='{"spec":{"storageLocation":"default"}}')
    refused(h)


def test_kopia_target_dotdot_escape(h):
    root = h.cfg["kopia"]["scratch_mount_root"]
    h.cfg["kopia"]["sources"][0]["target"] = f"{root}/../escape"
    refused(h)


def test_kopia_target_symlink_escape(h):
    root = h.cfg["kopia"]["scratch_mount_root"]
    (h.tmp / "outside").mkdir()
    os.symlink(h.tmp / "outside", f"{root}/link")
    h.cfg["kopia"]["sources"][0]["target"] = f"{root}/link/x"
    refused(h)


def test_kopia_target_root_itself_refused(h):
    h.cfg["kopia"]["sources"][0]["target"] = h.cfg["kopia"]["scratch_mount_root"]
    refused(h)


def test_cnpg_plugin_in_cluster_is_refused(h):
    h.cfg["cnpg"]["cluster_name"] = "styx-db"  # same as serverName
    refused(h)


SCENARIOS = {
    "prod-uid": lambda h: h.cfg.update(prod_cluster_uids=[UID]),
    "full-site": lambda h: h.cfg.update(mode="full-site"),
    "ns-styx": lambda h: h.cfg.update(namespace="styx"),
    "ns-foreign": lambda h: h.on(rf"^kubectl get namespace {NS}", out='{"metadata":{}}'),
    "velero-map": lambda h: h.cfg["velero"].update(include_namespaces=["styx", "kc"]),
    "velero-rw": lambda h: h.on(r"^kubectl get backupstorage", out='{"spec":{}}'),
    "velero-prod": lambda h: h.on(r"^velero backup get",
                                  out='{"spec":{"storageLocation":"default"}}'),
    "kopia-escape": lambda h: h.cfg["kopia"]["sources"][0].update(target="/etc"),
    "cnpg-tz": lambda h: h.cfg["cnpg"].update(target_time="2026-11-09T03:00:00"),
}


@pytest.mark.parametrize("name", SCENARIOS)
def test_guards_run_before_any_write(h, name):
    SCENARIOS[name](h)
    refused(h)


CONFIG_ERRORS = {
    "bad-table": lambda h: h.cfg["cnpg"].update(tables={"users; drop": "id"}),
    "bad-pk": lambda h: h.cfg["cnpg"].update(tables={"users": "id) --"}),
    "no-kopia-s3": lambda h: h.cfg["kopia"].pop("s3"),
    "no-velero-backup": lambda h: h.cfg["velero"].pop("backup"),
    "naive-incident": lambda h: h.cfg.update(incident_time="2026-11-09T03:00:00"),
}


@pytest.mark.parametrize("name", CONFIG_ERRORS)
def test_config_errors_refused_before_any_write(h, name):
    CONFIG_ERRORS[name](h)
    r = h.cli("run", "--confirm", RUN)
    assert r.returncode == 2, r.stderr
    assert h.writes() == []


def test_failed_namespace_create_aborts_before_restore(h):
    # Unreadable namespace (RBAC/transient) + create fails (AlreadyExists): it may be
    # someone else's namespace, so nothing may be restored into it.
    h.on(r"^kubectl create", code=1)
    r = h.cli("run", "--confirm", RUN)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "ABORTED" in r.stderr
    assert [c[:2] for c in h.writes()] == [["kubectl", "create"]]
    rep = json.loads((h.run_dir() / "report.json").read_text())
    assert rep["pass"] is False
    assert rep["steps"][-1]["result"] == "exit 1"


@pytest.mark.parametrize("step", [r"^kubectl apply", r"^velero restore create",
                                  r"^kopia .*snapshot restore"])
def test_failed_write_step_aborts(h, health, step):
    full_run_setup(h, health)
    h.on(step, code=1)
    r = h.cli("run", "--confirm", RUN)
    assert r.returncode == 3, r.stdout + r.stderr
    assert json.loads((h.run_dir() / "report.json").read_text())["pass"] is False


def test_error_after_writes_aborts_with_report(h, health):
    full_run_setup(h, health)
    h.on(r"^kopia .*snapshot list", out='[{"id": "s1"}]')  # no startTime
    r = h.cli("run", "--confirm", RUN)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "ABORTED" in r.stderr and "REFUSED" not in r.stderr
    rep = json.loads((h.run_dir() / "report.json").read_text())
    assert rep["pass"] is False
    assert (h.run_dir() / "report.md").exists()


def test_oserror_after_writes_aborts_with_report(fake_env, health, monkeypatch, capsys):
    # e.g. a restored file kopia left unreadable (mode 000) for the harness user.
    from drtest import checks, cli

    def unreadable(*a, **k):
        raise PermissionError(13, "Permission denied", "a.txt")

    full_run_setup(fake_env, health)
    fake_env.apply()
    monkeypatch.setattr(checks, "sha256_sample", unreadable)
    cfg = fake_env.tmp / "drtest.json"
    cfg.write_text(json.dumps(fake_env.cfg))
    assert cli.main(["-c", str(cfg), "run", "--confirm", RUN]) == 3
    assert "ABORTED" in capsys.readouterr().err
    assert json.loads((fake_env.run_dir() / "report.json").read_text())["pass"] is False
    assert (fake_env.run_dir() / "report.md").exists()


def test_non_executable_tool_is_a_failed_step(tmp_path):
    from drtest import run

    tool = tmp_path / "pg_amcheck"
    tool.write_text("#!/bin/sh\nexit 0\n")  # no x bit: PermissionError, even as root
    p = run.Runner(run.Sink({}))([str(tool)], step="amcheck")
    assert p.returncode == 126


def test_config_without_data_sources_refused(h):
    for k in ("cnpg", "velero", "kopia"):
        h.cfg.pop(k)
    refused(h)
