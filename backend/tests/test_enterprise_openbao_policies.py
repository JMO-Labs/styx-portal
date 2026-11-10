"""OpenBao policies and Kubernetes auth roles are least-privilege (issue #4)."""

import json
from pathlib import Path

import pytest

from tests.openbao_checks import OPENBAO, check_policy, policy_paths

POLICIES = OPENBAO / "policies"
BAD = Path(__file__).parent / "fixtures/openbao_bad"


def roles() -> dict[str, dict]:
    return {r["name"]: r for r in json.loads((OPENBAO / "auth-roles.json").read_text())}


def test_eso_read_policy_exact():
    assert policy_paths((POLICIES / "eso-read.hcl").read_text()) == {
        "kv/data/*": {"read"}, "kv/metadata/*": {"read", "list"}}


def test_raft_snapshot_policy_exact():
    assert policy_paths((POLICIES / "raft-snapshot.hcl").read_text()) == {
        "sys/storage/raft/snapshot": {"read"}}


@pytest.mark.parametrize("path", sorted(POLICIES.glob("*.hcl")), ids=lambda p: p.name)
def test_no_wildcard_root_or_sudo(path):
    assert check_policy(path.read_text()) == []


def test_wild_policy_fixture_rejected():
    errs = check_policy((BAD / "wild.hcl").read_text())
    assert any("wildcard" in e for e in errs) and any("sudo" in e for e in errs)


def test_auth_roles():
    rs = roles()
    assert {"eso", "raft-snapshot"} <= set(rs)
    for name, r in rs.items():
        assert set(r) == {"name", "bound_service_account_names",
                          "bound_service_account_namespaces", "policies", "token_ttl"}, name
        for key in ("bound_service_account_names", "bound_service_account_namespaces", "policies"):
            assert r[key] and all(v and "*" not in v for v in r[key]), (name, key)
        assert isinstance(r["token_ttl"], int) and 0 < r["token_ttl"] <= 3600, name
        for p in r["policies"]:
            assert (POLICIES / f"{p}.hcl").is_file(), (name, p)
    assert rs["raft-snapshot"]["token_ttl"] <= 900
    assert rs["eso"]["bound_service_account_names"] == ["external-secrets"]
    assert rs["eso"]["bound_service_account_namespaces"] == ["external-secrets"]
    assert rs["eso"]["policies"] == ["eso-read"]
    assert rs["raft-snapshot"]["bound_service_account_names"] == ["openbao-snapshot"]
    assert rs["raft-snapshot"]["bound_service_account_namespaces"] == ["openbao"]
    assert rs["raft-snapshot"]["policies"] == ["raft-snapshot"]
