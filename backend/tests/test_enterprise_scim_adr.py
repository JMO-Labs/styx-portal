"""ADR-0062 (D61): SCIM subset for the provisioning webhook (issue #105)."""

import json
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs/enterprise"
SCHEMA_DIR = DOCS / "schemas"
SCHEMA = SCHEMA_DIR / "scim-provisioning-v1.schema.json"


def adr_text() -> str:
    (path,) = (DOCS / "adr").glob("0062-*.md")
    return path.read_text()


def schema() -> dict:
    return json.loads(SCHEMA.read_text())


def valid_user() -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "externalId": "req-1001",
        "userName": "ignored.by.styx",
        "name": {"givenName": "Ada", "familyName": "Lovelace"},
        "emails": [{"value": "ada@example.mil", "primary": True}],
        "active": True,
        "urn:styx:scim:schemas:provisioning:1.0:Request": {
            "approvalId": "7b1d6c1e-0000-4000-8000-000000000001",
            "approverEmail": "boss@example.mil",
            "cardType": "CAC",
            "edipi": "1234567890",
            "groups": ["analysts"],
            "personType": "employee",
        },
    }


EXT = "urn:styx:scim:schemas:provisioning:1.0:Request"


def test_adr_sections_and_index():
    text = adr_text()
    for head in ("## Operations", "## Attributes", "## Idempotency",
                 "## Approval ID", "## Error model", "## Audit event"):
        assert head in text, head
    assert "Decision ID: D61" in text
    assert "no delete" in text.lower()
    index = (DOCS / "adr/README.md").read_text()
    assert "0062-" in index


def test_adr_maps_every_d21_field():
    text = adr_text()
    for field in ("first name", "last name", "email", "card type", "EDIPI",
                  "groups", "approving manager", "end date"):
        assert field.lower() in text.lower(), field
    for status in ("400", "401", "403", "404", "409", "422", "429"):
        assert status in text, status


def test_schema_is_committed_and_wellformed():
    s = schema()
    assert s["$schema"].startswith("https://json-schema.org/draft/2020-12")
    assert s["$id"]
    assert set(s["$defs"]) >= {"user", "patchOp", "error", "auditEvent"}


def test_schema_has_no_delete_op():
    ops = schema()["$defs"]["patchOp"]["properties"]["op"]["enum"]
    assert "remove" not in ops
    assert set(ops) == {"replace"}


def jsonschema():
    return pytest.importorskip("jsonschema")


def check(defn: str, doc: dict) -> None:
    js = jsonschema()
    root = schema()
    js.validate(doc, {"$ref": f"#/$defs/{defn}", "$defs": root["$defs"]},
                cls=js.Draft202012Validator)


def test_valid_user_accepted():
    check("user", valid_user())


@pytest.mark.parametrize("mutate", [
    lambda u: u[EXT].update(cardType="CAC", edipi=None) or u[EXT].pop("edipi"),
    lambda u: u[EXT].update(cardType="PIV", edipi="1234567890"),
    lambda u: u[EXT].update(cardType="MAGSTRIPE"),
    lambda u: u[EXT].update(personType="contractor"),
    lambda u: u[EXT].update(groups=[]),
    lambda u: u[EXT].update(unknown="x"),
    lambda u: u.update(extra="x"),
    lambda u: u[EXT].pop("approvalId"),
])
def test_invalid_user_rejected(mutate):
    js = jsonschema()
    u = valid_user()
    mutate(u)
    with pytest.raises(js.ValidationError):
        check("user", u)


def test_contractor_with_end_date_ok():
    u = valid_user()
    u[EXT].update(personType="contractor", endDate="2027-03-31")
    check("user", u)


def test_disable_patch_and_error_and_audit():
    check("patchOp", {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "path": "active", "value": False}],
        EXT: {"approvalId": "7b1d6c1e-0000-4000-8000-000000000002"},
    })
    check("error", {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
        "status": "409", "scimType": "uniqueness", "detail": "x",
        "styxCode": "IDEMPOTENCY_CONFLICT",
    })
    check("auditEvent", {
        "event": "provision.user.create", "timestamp": "2026-11-12T10:00:00Z",
        "requestId": "r1", "idempotencyKey": "k1", "approvalId": "a1",
        "approver": "boss@example.mil", "clientCertFingerprint": "ab" * 32,
        "sourceIp": "203.0.113.5", "outcome": "success", "httpStatus": 201,
        "resource": {"type": "User", "externalId": "req-1001"},
    })


def test_schema_file_names_in_docs():
    assert re.search(r"docs/enterprise/schemas/scim-provisioning-v1\.schema\.json",
                     adr_text())
