"""Doc-lint for the full-site restore runbook (issue #14, ADR-0037, R03)."""

import re
from pathlib import Path

import pytest

from tests.test_enterprise_docs import INVENTED_REF

DOCS = Path(__file__).resolve().parents[2] / "docs/enterprise"
RUNBOOK = DOCS / "runbooks/full-site-restore.md"
TBD = "TBD (owner input)"
UNPROVEN = "unproven until #15"
SECTIONS = [
    "Scope and decisions", "RTO clock", "Roles", "Before you start", "Rebuild order",
    "Steps", "Control-plane-only loss", "Evidence", "Follow-up IaC",
]
ROLES = [
    "Incident commander", "Platform admin (executor)", "Escrow custodian (2-person)",
    "Shamir recovery key holder", "Help desk (validation and comms)",
    "ISSO (evidence witness and sign-off)",
]


def text() -> str:
    return RUNBOOK.read_text()


def h2(body: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}\n.*?(?=^## |\Z)", body, re.M | re.S)
    assert m, f"section {title} missing"
    return m.group(0)


def step(body: str, n: int) -> str:
    m = re.search(rf"^### Step {n}:.*?(?=^### |^## |\Z)", body, re.M | re.S)
    assert m, f"step {n} missing"
    return m.group(0)


def adr(num: str) -> str:
    (path,) = (DOCS / "adr").glob(f"{num}-*.md")
    return path.read_text()


def row(body: str, key: str) -> str:
    m = re.search(rf"^\| {re.escape(key)} \|.*$", body, re.M)
    assert m, f"row {key} missing"
    return m.group(0)


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def test_runbook_exists_and_short():
    assert RUNBOOK.is_file()
    assert len(text().splitlines()) < 500


def test_sections_in_order():
    found = re.findall(r"^## (.+)$", text(), re.M)
    assert [s for s in found if s in SECTIONS] == SECTIONS


def test_steps_0_to_10_in_order():
    nums = [int(n) for n in re.findall(r"^### Step (\d+):", text(), re.M)]
    assert nums == list(range(11))
    assert "### Step 11" not in text()


@pytest.mark.parametrize("n", range(11))
def test_each_step_has_fields(n):
    body = step(text(), n)
    for field in ("Depends on:", "Owner role:", "Estimate:", "Evidence:", "Done when:"):
        assert field in body, f"step {n}: {field}"
    estimate = re.search(r"^Estimate:.*$", body, re.M).group(0)
    assert UNPROVEN in estimate


def test_rebuild_table_estimates_unproven():
    rows = re.findall(r"^\| (?:10|[0-9]) \|.*$", h2(text(), "Rebuild order"), re.M)
    assert len(rows) == 11
    for r in rows:
        assert UNPROVEN in r, r


def test_decisions_named():
    body = h2(text(), "Scope and decisions")
    for key in ("A1", "B1", "C1", "D1", "ADR-0037", "ADR-0042"):
        assert key in body, key


def test_rto_clock_d1():
    body = h2(text(), "RTO clock").lower()
    for word in ("hardware", "ready", "priority", "login", "desktop"):
        assert word in body, word


def test_roles_are_placeholders():
    body = h2(text(), "Roles")
    for role in ROLES:
        c = cells(row(body, role))
        assert c[1] == TBD and c[2] == TBD, role


def test_owner_inputs_are_placeholders():
    body = h2(text(), "Before you start")
    lines = body.splitlines()
    assert any("second escrow location" in ln.lower() and TBD in ln for ln in lines)
    assert any("wan bandwidth" in ln.lower() and TBD in ln for ln in lines)
    for item in ("Kopia password", "static seal key", "RKE2 token", "Velero repo password"):
        assert item in body, item


def test_openbao_step_static_seal():
    body = step(text(), 3)
    for item in ('seal "static"', "bao operator raft snapshot restore -force",
                 "ClusterSecretStore"):
        assert item in body, item
    for ln in body.splitlines():
        if "TPM" in ln:
            assert re.search(r"cannot|not restor", ln, re.I), ln


def test_cnpg_step():
    body = step(text(), 6)
    assert "bootstrap.recovery" in body and "barman" in body.lower()
    values = re.findall(r'targetTime:\s*"?([^"\s]+)', text())
    assert values
    for v in values:
        assert v.endswith("Z"), v


def test_velero_step_excludes_platform():
    body = step(text(), 7)
    for item in ("rook-ceph", "openbao", "kube-system"):
        assert item in body, item
    assert "exclude" in body.lower()


def test_homes_window_both_rates():
    body = step(text(), 8)
    for item in ("kopia snapshot restore", "4.5 h", "1 Gbit/s", "9 h", "500 Mbit/s"):
        assert item in body, item


def test_cluster_reset_only_in_cp_section():
    full = text()
    cp = h2(full, "Control-plane-only loss")
    assert "--cluster-reset" in cp
    assert "--cluster-reset" not in full.replace(cp, "")


def test_evidence_matches_harness_schema():
    body = h2(text(), "Evidence")
    for item in ("schema_version", '"1.0"', '"id"', '"start"', '"end"', '"actor"',
                 '"command"', '"result"', "docs/enterprise/evidence/dr/", "CP-4", "CP-9",
                 "CP-10", "R03", "ISSO"):
        assert item in body, item
    for word in ("incident commander", "seal number", "annually"):
        assert word in body.lower(), word


def test_followup_iac_listed():
    body = h2(text(), "Follow-up IaC")
    for item in ("#24", "#4", "BSL", "repo password", "snapshot", "RGW", "SC-28"):
        assert item in body, item


@pytest.mark.parametrize(
    "pattern",
    [r"AKIA[0-9A-Z]{16}", r"-----BEGIN", r"[0-9a-fA-F]{32,}",
     r"(password|secret|token)\s*[:=]\s*(?!<)\S{8,}"],
)
def test_no_secrets_in_runbook(pattern):
    assert not re.search(pattern, text(), re.I), pattern


def test_no_invented_exception_ref():
    assert not INVENTED_REF.search(text())


def test_runbook_adr_refs_exist():
    existing = {p.name[:4] for p in (DOCS / "adr").glob("0[0-9][0-9][0-9]-*.md")}
    refs = re.findall(r"ADR-(\d{4})", text())
    assert refs
    for num in refs:
        assert num in existing, f"ADR-{num}"


def test_control_matrix_links_runbook():
    cm = (DOCS / "control-matrix.md").read_text()
    for ctl in ("CP-9", "CP-10"):
        r = row(cm, ctl)
        assert "runbooks/full-site-restore.md" in r, ctl
        assert r.rstrip().endswith("| Planned |"), ctl
    assert "annually" in row(cm, "CP-4").lower()


def test_readme_and_adrs_link_runbook():
    assert "runbooks/full-site-restore.md" in (DOCS / "README.md").read_text()
    a37, a42 = adr("0037"), adr("0042")
    assert "full-site-restore" in a37
    assert 'seal "static"' in a42
    for a in (a37, a42):
        assert "- Status: Accepted" in a
