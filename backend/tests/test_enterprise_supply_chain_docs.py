"""Doc-lint for the image supply chain ADR, runbook and control matrix rows (#152)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENT = ROOT / "docs/enterprise"
RUNBOOK = ENT / "runbooks/image-supply-chain.md"


def _adr() -> Path:
    (path,) = (ENT / "adr").glob("0069-*.md")
    return path


def test_adr_linked_from_0029_0030_and_index():
    name = _adr().name
    for num in ("0029", "0030"):
        (path,) = (ENT / "adr").glob(f"{num}-*.md")
        assert name in path.read_text()
    assert name in (ENT / "adr/README.md").read_text()


def test_adr_records_sibling_choices():
    text = _adr().read_text().lower()
    for word in ("harbor", "digest", "kyverno", "allowlist", "recycle", "fail open"):
        assert word in text


def test_runbook_sections():
    text = RUNBOOK.read_text().lower()
    for word in ("nightly", "trivy", ".trivyignore", "kyverno", "forced recycle", "verify"):
        assert word in text


def test_nav_has_runbook():
    assert "enterprise/runbooks/image-supply-chain.md" in (ROOT / "zensical.toml").read_text()


def test_matrix_rows_point_to_artifacts():
    text = (ENT / "control-matrix.md").read_text()
    for ctl in ("SI-7", "CM-14", "SI-2", "RA-5"):
        rowtxt = re.search(rf"^\| {ctl} \|.*$", text, re.M).group(0)
        assert "runbooks/image-supply-chain.md" in rowtxt, ctl
    for ctl in ("SI-7", "CM-14"):
        rowtxt = re.search(rf"^\| {ctl} \|.*$", text, re.M).group(0)
        for ref in ("images-nightly.yml", "deploy/enterprise/kyverno", "image_digest.py"):
            assert ref in rowtxt, (ctl, ref)
    assert "cve_recycle.py" in re.search(r"^\| SI-2 \|.*$", text, re.M).group(0)
