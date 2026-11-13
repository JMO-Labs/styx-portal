"""Doc-lint for the Wiki.js/Matrix ADR, runbook and control matrix rows (#282)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENT = ROOT / "docs/enterprise"
RUNBOOK = ENT / "runbooks/wikijs-matrix.md"


def _adr() -> Path:
    (path,) = (ENT / "adr").glob("0071-wikijs-and-matrix-implementation.md")
    return path


def test_adr_content_and_index():
    text = _adr().read_text().lower()
    assert "decision id: d70" in text
    for word in ("oidc-only", "cnpg", "room adapter", "smtp", "adr-0059", "federation", "seed"):
        assert word in text, word
    assert _adr().name in (ENT / "adr/README.md").read_text()


def test_runbook_sections():
    text = RUNBOOK.read_text()
    for word in (
        "kv/styx/wikijs/oidc", "styx/synapse/secrets", "MATRIX_NOTIFY_TOKEN",
        "MATRIX_NOTIFY_ROOM_ID", "ScheduledBackup", "Velero", "excludedNamespaces",
    ):
        assert word in text, word


def test_nav_has_runbook():
    assert "enterprise/runbooks/wikijs-matrix.md" in (ROOT / "zensical.toml").read_text()


def test_matrix_rows_point_to_artifacts():
    text = (ENT / "control-matrix.md").read_text()
    for ctl in ("IA-2", "AC-2", "AU-6", "IR-4", "CP-9", "SC-7"):
        row = re.search(rf"^\| {ctl} \|.*$", text, re.M).group(0)
        assert "runbooks/wikijs-matrix.md" in row, ctl
        assert "ADR-0071" in row or "0071" in row, ctl


def test_velero_does_not_exclude_namespaces():
    sched = (ROOT / "deploy/enterprise/backup/velero-schedules.yaml").read_text()
    for line in re.findall(r"excludedNamespaces:.*", sched):
        assert "wikijs" not in line and "matrix" not in line
