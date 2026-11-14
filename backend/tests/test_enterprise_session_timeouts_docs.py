"""ADR-0080 (D79), control matrix AC-11/AC-12 and the session-timeouts runbook (issue #255)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/enterprise"
RUNBOOK = DOCS / "runbooks/session-timeouts.md"


def adr() -> str:
    (path,) = (DOCS / "adr").glob("0080-*.md")
    return path.read_text()


def row(cm: str, ctl: str) -> str:
    return re.search(rf"^\| {re.escape(ctl)} \|.*$", cm, re.M).group(0)


def test_adr_0080_decisions():
    text = adr()
    assert "- Status: Proposed" in text and "Decision ID: D79" in text
    for phrase in ("15 min", "no TLS resumption", "2 h", "12 h", "STYX_LOCK_IDLE_S",
                   "SESSION_DISCONNECT_MAX_H", "SESSION_MAX_H", "capped"):
        assert phrase in text, phrase
    assert "[D79](0080-" in (DOCS / "adr/README.md").read_text()


def test_matrix_rows_link_code_and_tests():
    cm = (DOCS / "control-matrix.md").read_text()
    for ctl, paths in {
        "AC-11": ("0080", "agent/gateway_idlelock.py", "backend/app/services/session_policy.py",
                  "backend/tests/test_unlock.py", "agent/tests/test_gateway_idlelock.py"),
        "AC-12": ("0080", "backend/app/services/session_reaper.py",
                  "backend/tests/test_session_reaper.py"),
    }.items():
        for p in paths:
            assert p in row(cm, ctl), (ctl, p)
            if "/" in p:
                assert (ROOT / p).exists(), p


def test_runbook_content():
    text = RUNBOOK.read_text()
    for phrase in ("idle_lock_minutes", "STYX_LOCK_IDLE_S", "SESSION_DISCONNECT_MAX_H",
                   "SESSION_MAX_H", "SESSION_WARN_MIN", "session.lock", "session.unlock",
                   "session.unlock_denied", "session.stop", "max_duration", "disconnected",
                   "Troubleshooting", "15"):
        assert phrase in text, phrase
