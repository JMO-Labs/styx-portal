"""ADR-0082 (D81), Keycloak admin client permissions, control matrix and runbook (issue #123)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/enterprise"
KC = DOCS / "keycloak-admin-client.md"
RUNBOOK = DOCS / "runbooks/provisioning-webhook.md"


def adr() -> str:
    (path,) = (DOCS / "adr").glob("0082-*.md")
    return path.read_text()


def row(cm: str, ctl: str) -> str:
    return re.search(rf"^\| {re.escape(ctl)} \|.*$", cm, re.M).group(0)


def test_adr_0082_decisions():
    text = adr()
    assert "- Status: Proposed" in text and "Decision ID: D81" in text
    for phrase in ("fingerprint", "Idempotency-Key", "body_hash", "POSIX_UID_MIN", "100000",
                   "max(ever allocated)", "exact", "review queue", "ADR-0051"):
        assert phrase in text, phrase
    assert "[D81](0082-" in (DOCS / "adr/README.md").read_text()


def test_keycloak_client_doc_lists_granted_and_denied():
    text = KC.read_text()
    for phrase in ("Granted", "Denied", "manage-users", "role mapping", "realm settings",
                   "KEYCLOAK_ADMIN_GROUPS", "KC_ADMIN_CLIENT_SECRET", "ADR-0051"):
        assert phrase in text, phrase


def test_matrix_rows_cite_adr_and_code():
    cm = (DOCS / "control-matrix.md").read_text()
    for ctl in ("AC-2", "AC-2(1)", "AC-6", "IA-4", "SI-10", "AU-2"):
        assert "0082" in row(cm, ctl), ctl
    for ctl, paths in {
        "AC-2(1)": ("backend/app/routers/provision.py", "backend/app/services/provisioning.py"),
        "AC-6": ("keycloak-admin-client.md",),
        "IA-4": ("backend/app/services/card_binding.py", "backend/app/services/posix_uid.py"),
        "SI-10": ("backend/tests/test_provision_webhook.py",),
        "AU-2": ("backend/tests/test_provision_webhook.py",),
    }.items():
        for p in paths:
            assert p in row(cm, ctl), (ctl, p)
            if p.startswith("backend/"):
                assert (ROOT / p).exists(), p


def test_runbook_content():
    text = RUNBOOK.read_text()
    for phrase in ("PROVISION_BEARER_TOKEN", "PROVISION_CLIENT_CERT_FINGERPRINTS",
                   "openssl x509", "/api/admin/card-reviews", "resolve", "card.review.queued",
                   "bearer_invalid", "cert_not_allowed", "Troubleshooting"):
        assert phrase in text, phrase
