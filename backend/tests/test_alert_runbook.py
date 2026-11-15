"""Every alert in the SLO rules must have a runbook section and docs must be in the nav."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _alerts() -> set[str]:
    text = (ROOT / "deploy/k8s/slo-rules.yaml").read_text()
    return set(re.findall(r"- alert: (\w+)", text))


def test_every_slo_alert_has_runbook_section():
    runbook = (ROOT / "docs/operate/alert-runbook.md").read_text()
    headings = set(re.findall(r"^## (\w+)\s*$", runbook, re.M))
    assert _alerts(), "no alerts parsed"
    assert _alerts() <= headings, _alerts() - headings


def test_slo_page_states_budget_and_rtt_scope():
    slo = (ROOT / "docs/operate/slo.md").read_text()
    assert "14.5" in slo
    assert "not input-to-photon" in slo


def test_pages_in_nav():
    nav = (ROOT / "zensical.toml").read_text()
    assert "operate/slo.md" in nav and "operate/alert-runbook.md" in nav


def test_changelog_mentions_slo_docs():
    assert "alert-runbook" in (ROOT / "CHANGELOG.md").read_text()
