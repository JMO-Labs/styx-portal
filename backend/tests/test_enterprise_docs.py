"""Doc-lint for docs/enterprise: ADR acceptance and owner Rounds 1-5 amendments (issue #1)."""

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs/enterprise"
ADR = DOCS / "adr"
DATE = "2026-11-09"
TODO_R05 = "TODO (owner): issuer, date, scope"
SOURCE = "Owner approval Rounds 1-5, 2026-11-09 (issue #1)"
INVENTED_REF = re.compile(
    r"exception (ref|reference|no\.?|number)\s*[:#]\s*[A-Z0-9-]{4,}", re.I
)


def adr(num: str) -> str:
    (path,) = ADR.glob(f"{num}-*.md")
    return path.read_text()


def adr_files() -> list[Path]:
    return sorted(ADR.glob("0[0-9][0-9][0-9]-*.md"))


def status(text: str) -> str:
    return re.search(r"^- Status: (.+)$", text, re.M).group(1).strip()


def section(text: str, num: int) -> str:
    """Body of the design.md '## <num>.' section."""
    m = re.search(rf"^## {num}\..*?(?=^## |\Z)", text, re.M | re.S)
    assert m, f"design.md section {num} missing"
    return m.group(0)


def row(text: str, key: str) -> str:
    m = re.search(rf"^\| {re.escape(key)} \|.*$", text, re.M)
    assert m, f"row {key} missing"
    return m.group(0)


def has(text: str, phrase: str) -> bool:
    return phrase.lower() in text.lower()


def test_all_original_adrs_accepted():
    originals = sorted(ADR.glob("00[0-5][0-9]-*.md"))
    assert len(originals) == 59
    assert len(adr_files()) == 64
    for path in adr_files():
        if path.name >= "0062-":  # later ADRs await owner acceptance
            continue
        text = path.read_text()
        assert "Status: Proposed" not in text, path.name
        if not path.name.startswith("0045-"):
            assert "- Status: Accepted" in text, path.name
            assert f"- Accepted: {DATE}" in text, path.name


def test_adr_0045_superseded_by_0060():
    assert "- Status: Superseded by ADR-0060" in adr("0045")


def test_adr_0060_takeover_rules():
    text = adr("0060")
    assert SOURCE in text
    assert "Supersedes: ADR-0045" in text
    assert "- Status: Accepted" in text
    assert "Decision ID: D45a" in text
    for phrase in ("platform admin", "help desk", "banner", "reason", "Elastic",
                   "security officer", "monthly"):
        assert has(text, phrase), phrase
    # The exclusion must be explicit, not just an omission.
    assert re.search(
        r"auditor.{0,40}group manager.{0,40}(may not|not permitted)", text, re.I | re.S
    )


def test_adr_0061_osd_encryption():
    text = adr("0061")
    assert SOURCE in text
    assert "- Status: Accepted" in text
    assert "Decision ID: D60" in text
    for phrase in ("dm-crypt", "OpenBao", "SC-28", "SC-12", "every"):
        assert has(text, phrase), phrase


def test_adr_0063_cosign_custody():
    text = adr("0063")
    assert "Decision ID: D62" in text
    assert "- Status: Proposed" in text  # awaits owner acceptance; not backdated
    for phrase in ("transit", "exportable=false", "ci-cosign", "rotate",
                   "min_encryption_version", "30 days", "90 days", "rationale"):
        assert has(text, phrase), phrase
    for num in ("0028", "0029", "0030"):
        assert "ADR-0063" in adr(num), num
    s7 = section((DOCS / "design.md").read_text(), 7)
    assert "Closed (Phase 3)" in s7 and "ADR-0063" in s7


def test_adr_0064_keycloak_x509():
    text = adr("0064")
    assert text.startswith("# ADR-0064: Keycloak X.509")
    assert "Decision ID: D63" in text
    for phrase in ("Client-Cert", "haproxy", "IA-2(12)"):
        assert has(text, phrase), phrase
    index = (ADR / "README.md").read_text()
    assert "[D63](0064-keycloak-x509" in index
    assert "ADR-0064 (D63)" in (DOCS / "design.md").read_text()


def test_adr_index_matches_files():
    index = (ADR / "README.md").read_text()
    older = [ln for ln in index.splitlines() if "(0062-" not in ln and "(0063-" not in ln]
    assert "| Proposed |" not in "\n".join(older)
    assert f"accepted {DATE}" in index.lower()
    rows = dict(re.findall(r"^\| \[D\w+\]\(([^)]+)\) \|[^|]+\| ([^|]+) \|", index, re.M))
    names = {p.name for p in adr_files()}
    assert set(rows) == names
    for name, idx_status in rows.items():
        assert idx_status.strip() == status((ADR / name).read_text()), name


@pytest.mark.parametrize(
    ("num", "phrases"),
    [
        ("0015", ["CAC", "PIV-I", "no fallback", "break-glass"]),
        ("0016", ["exact", "EDIPI", "admin review", "name-only"]),
        ("0017", ["fail closed", "nextUpdate", "alert", "break-glass"]),
        ("0019", ["90 days"]),
        ("0020", ["90 days"]),
        ("0021", ["90 days"]),
        ("0022", ["35 days", "90 days after disable"]),
        ("0023", ["security officer", "2 business days", "auto-suspend"]),
        ("0024", ["security officer", "2 business days", "auto-suspend"]),
        ("0011", ["R05", TODO_R05]),
    ],
)
def test_identity_amendments(num, phrases):
    text = adr(num)
    assert SOURCE in text
    for phrase in phrases:
        assert has(text, phrase), f"{num}: {phrase}"


@pytest.mark.parametrize(
    ("num", "phrases"),
    [
        ("0028", ["7 days", "Phase 3", "cosign"]),
        ("0029", ["7 days", "Phase 3", "cosign"]),
        ("0030", ["7 days", "Phase 3", "cosign"]),
        ("0031", ["D47", "SR-IOV"]),
        ("0032", ["D47", "SR-IOV"]),
        ("0033", ["ADR-0061"]),
        ("0054", ["ADR-0061"]),
        ("0055", ["ADR-0061"]),
        ("0034", ["read-only", "handoff", "ADR-0022"]),
        ("0035", ["read-only", "handoff", "ADR-0022"]),
        ("0038", ["written", "security officer"]),
        ("0057", ["Pod Security Admission", "control-matrix.md", "upstream"]),
        ("0058", ["Pod Security Admission", "control-matrix.md", "upstream"]),
        ("0012", ["Phase 1", "ACME"]),
        ("0049", ["Phase 1", "ACME"]),
    ],
)
def test_desktop_and_data_amendments(num, phrases):
    text = adr(num)
    assert SOURCE in text
    for phrase in phrases:
        assert has(text, phrase), f"{num}: {phrase}"


def test_r05_placeholder_not_invented():
    design = (DOCS / "design.md").read_text()
    for text in (adr("0011"), section(design, 8)):
        assert TODO_R05 in text
        assert not INVENTED_REF.search(text)


def test_design_status_and_sections():
    design = (DOCS / "design.md").read_text()
    header = design.split("\n## ", 1)[0]
    assert "Accepted" in header and DATE in header
    assert "Draft for owner approval" not in design
    s7 = section(design, 7)
    for phrase in ("X.509", "SCIM", "Phase 2", "Phase 3", "cosign"):
        assert has(s7, phrase), phrase
    s8 = section(design, 8)
    for rid in ("R01", "R02", "R03", "R04", "R05", "R06"):
        assert "Accepted" in row(s8, rid), rid
    for phrase in ("uncategorised", "card removal", "annually", "eMASS evidence",
                   "2 business days"):
        assert has(s8, phrase), phrase
    s5 = section(design, 5)
    assert has(row(s5, "D60"), "dm-crypt")
    assert "ADR-0060" in row(s5, "D45")
    # Non-goals must not forbid admin takeover; session sharing (v2) stays.
    s2 = section(design, 2)
    assert "session sharing/collaboration (v2)" in s2
    assert not re.search(r"(shadow|takeover|take control)", s2.split("Anti-goals")[0], re.I)


def test_control_matrix_amendments():
    cm = (DOCS / "control-matrix.md").read_text()
    ac17 = row(cm, "AC-17")
    assert "0060" in ac17 and "0045" not in ac17
    for phrase in ("banner", "reason", "monthly"):
        assert has(ac17, phrase), phrase
    for ctl in ("AU-2", "AU-3", "AU-6", "AU-12"):
        assert has(row(cm, ctl), "takeover"), ctl
    assert has(row(cm, "AU-6"), "monthly")
    assert "0061" in row(cm, "SC-28")
    for ctl in ("SI-2", "SI-7", "CM-14"):
        assert "0063" in row(cm, ctl), ctl
    assert has(row(cm, "SI-2"), "30 d") and has(row(cm, "SI-2"), "90 d")
    assert re.search(r"^\| CM-(6|7) \|.*Pod Security Admission.*0057", cm, re.M)
    assert has(row(cm, "SC-7(5)"), "uncategorised")
    assert has(row(cm, "AC-11"), "card removal")
    assert has(row(cm, "CP-4"), "annually")
    assert has(row(cm, "IA-12"), "2 business days")
    assert has(row(cm, "AC-2(4)"), "2 business days")
    assert TODO_R05 in row(cm, "SC-13")
    assert not INVENTED_REF.search(cm)
    intro = cm.split("\n## ", 1)[0]
    assert "Proposed" not in intro and "Accepted" in intro


def test_enterprise_readme():
    text = (DOCS / "README.md").read_text()
    assert "D01-D60" in text and "Accepted" in text and "Proposed" not in text


def test_no_dangling_adr_refs():
    existing = {p.name[:4] for p in adr_files()}
    texts = [(DOCS / "design.md").read_text(), (DOCS / "control-matrix.md").read_text()]
    texts += [p.read_text() for p in adr_files()]
    for text in texts:
        for group in re.findall(r"ADR-(\d{4}(?:, \d{4})*)", text):
            for num in group.split(", "):
                assert num in existing, f"ADR-{num}"
        for num in re.findall(r"adr/(\d{4})", text):
            assert num in existing, f"adr/{num}"
    design = (DOCS / "design.md").read_text()
    ids = re.findall(r"^\| (D\d\d) \|", section(design, 5), re.M)
    adr_ids = [status_id for p in adr_files()
               for status_id in re.findall(r"^- Decision ID: (\S+)$", p.read_text(), re.M)]
    for did in ids:
        assert adr_ids.count(did) == 1, did


def test_harbor_phase1_docs():
    """Issue #5: Harbor IaC is documented, ADR-0029 decision unchanged."""
    text = adr("0029")
    assert status(text) == "Accepted"
    assert "## Implementation note (Phase 1, #5)" in text
    cm = (DOCS / "control-matrix.md").read_text()
    for ctl in ("SR-3", "RA-5"):
        assert "deploy/enterprise/harbor" in row(cm, ctl), ctl
        assert has(row(cm, ctl), "implemented in code, not deployed"), ctl
    assert has(row(cm, "SC-8"), "WireGuard")
    restore = (DOCS / "runbooks/full-site-restore.md").read_text()
    assert "operate/harbor-enterprise.md" in restore
    root = DOCS.parents[1]
    assert (root / "docs/operate/harbor-enterprise.md").is_file()
    assert "operate/harbor-enterprise.md" in (root / "zensical.toml").read_text()
