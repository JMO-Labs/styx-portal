"""Teardown deletes only run-labelled objects in a Guard-2 namespace (issue #15)."""

from .conftest import NS, RUN

OWN = '{"metadata":{"labels":{"styx.io/dr-run":"t1","styx.io/dr-scratch":"true"}}}'


def test_teardown_only_run_labelled(h):
    h.on(rf"^kubectl get namespace {NS}", out=OWN)
    r = h.cli("teardown", "--confirm", RUN)
    assert r.returncode == 0, r.stderr
    deletes = [c for c in h.calls() if "delete" in c]
    assert deletes
    for c in deletes:
        assert c[0] == "kubectl"
        assert c[c.index("-l") + 1] == f"styx.io/dr-run={RUN}"
        assert c[c.index("--field-selector") + 1] == f"metadata.name={NS}"


def test_teardown_skips_foreign_namespace(h):
    h.on(rf"^kubectl get namespace {NS}", out='{"metadata":{"labels":{}}}')
    r = h.cli("teardown", "--confirm", RUN)
    assert r.returncode == 2
    assert h.writes() == []


def test_teardown_refuses_prod_namespace(h):
    h.cfg["namespace"] = "styx"
    r = h.cli("teardown", "--confirm", RUN)
    assert r.returncode == 2
    assert h.writes() == []


def test_teardown_requires_confirm(h):
    assert h.cli("teardown").returncode != 0
    assert h.calls() == []


def test_teardown_failed_delete_exits_3(h):
    h.on(rf"^kubectl get namespace {NS}", out=OWN)
    h.on(r"^kubectl delete", code=1)
    r = h.cli("teardown", "--confirm", RUN)
    assert r.returncode == 3
    assert "ABORTED" in r.stderr and "Traceback" not in r.stderr
