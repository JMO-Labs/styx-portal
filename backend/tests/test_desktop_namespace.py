"""Desktop namespace PSA exception manifest and control matrix (ADR-0057, CM-6/CM-7)."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "deploy/enterprise/desktop/namespace.yaml"
MATRIX = ROOT / "docs/enterprise/control-matrix.md"
PSA = "pod-security.kubernetes.io/"


def _labels() -> dict:
    doc = yaml.safe_load(MANIFEST.read_text())
    assert doc["kind"] == "Namespace"
    assert doc["metadata"]["name"] == "desktop"
    return doc["metadata"]["labels"]


def test_psa_labels():
    labels = _labels()
    assert labels[PSA + "enforce"] == "baseline"
    assert labels[PSA + "warn"] == "restricted"
    assert labels[PSA + "audit"] == "restricted"


def test_enforce_not_privileged():
    assert _labels()[PSA + "enforce"] != "privileged"


def test_manifest_comment_names_exception():
    text = MANIFEST.read_text()
    comment = "\n".join(line for line in text.splitlines() if line.lstrip().startswith("#"))
    for word in ("ADR-0057", "CM-6", "CM-7", "rootless", "non-root", "hostPath", "privileged"):
        assert word in comment


def test_matrix_rows_reference_manifest():
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| (CM-[67]) \|.*$", MATRIX.read_text(), re.M)}
    for cm in ("CM-6", "CM-7"):
        row = rows[cm]
        assert "deploy/enterprise/desktop/namespace.yaml" in row
        assert "non-root UID" in row
        assert "no privileged" in row and "hostPath" in row
