"""A11y checklist, conformance summary, ADR-0081 and control matrix row (issue #291)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/enterprise"
PAGES = ("accessibility-checklist.md", "accessibility-conformance.md")


def test_checklist_covers_keyboard_and_screen_reader_per_page():
    text = (DOCS / PAGES[0]).read_text()
    for phrase in ("Tab order", "Focus visible", "No keyboard trap", "Skip", "Escape", "Dialogs",
                   "NVDA", "Orca", "Landmarks", "Headings", "Accessible names", "Live regions",
                   "Pass/Fail/N/A", "/login", "/setup", "/connecting", "settings:", "/shell.html"):
        assert phrase in text, phrase
    assert re.search(r"^\| .* \| (Pending|Pass|Fail|N/A) \|", text, re.M)


def test_conformance_table_and_evidence():
    text = (DOCS / PAGES[1]).read_text()
    for phrase in ("WCAG 2.1 AA", "Section 508", "Supports", "Partially Supports", "Does not support",
                   "e2e/tests/a11y.spec.ts", "a11y", "ci.yml", "pull/392", "0081-"):
        assert phrase in text, phrase
    assert (ROOT / "e2e/tests/a11y.spec.ts").exists()
    assert re.search(r"^\| 1\.1\.1 \|", text, re.M)


def test_adr_0081():
    (path,) = (DOCS / "adr").glob("0081-accessibility-wcag-2-1-aa-axe-gate.md")
    text = path.read_text()
    assert "- Status: Proposed" in text and "Decision ID: D80" in text
    for phrase in ("wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "serious", "critical", "color-contrast", "jsdom"):
        assert phrase in text, phrase
    assert "[D80](0081-" in (DOCS / "adr/README.md").read_text()


def test_matrix_row_and_nav():
    cm = (DOCS / "control-matrix.md").read_text()
    (row,) = re.findall(r"^\| Section 508.*$", cm, re.M)
    for p in ("0081", "accessibility-checklist.md", "accessibility-conformance.md"):
        assert p in row, p
    nav = (ROOT / "zensical.toml").read_text()
    for p in PAGES:
        assert f"enterprise/{p}" in nav
