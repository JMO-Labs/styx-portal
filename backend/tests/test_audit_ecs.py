"""ECS JSON stdout emitter for audit events (styx-portal#11)."""
import hashlib
import io
import json
import logging
import uuid

import pytest

from app.models import User
from app.services.audit import audit
from app.services.audit_ecs import dlp_event, egress_event


@pytest.fixture
def lines():
    """Capture the raw lines written by the styx.audit logger."""
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("styx.audit")
    log.addHandler(h)
    yield lambda: [ln for ln in buf.getvalue().splitlines() if ln]
    log.removeHandler(h)


@pytest.mark.asyncio
async def test_audit_emits_one_ecs_line(session, lines):
    await audit(session, "auth.login", user_id="u1")
    (raw,) = lines()
    assert json.loads(raw)["event"]["dataset"] == "styx.audit"


@pytest.mark.asyncio
async def test_ecs_core_fields(session, lines):
    await audit(session, "auth.login", user_id="u1", actor_ip="10.0.0.9",
                resource="r1", detail={"ok": True})
    ev = json.loads(lines()[0])
    assert ev["@timestamp"].endswith("Z")
    assert uuid.UUID(ev["event"]["id"]).version == 4
    assert ev["event"]["action"] == "auth.login"
    assert ev["event"]["kind"] == "event"
    assert ev["event"]["module"] == "styx"
    assert ev["event"]["provider"] == "styx-portal"
    assert ev["source"]["ip"] == "10.0.0.9"
    assert ev["styx"]["audit"]["resource"] == "r1"
    assert ev["styx"]["audit"]["detail"] == {"ok": True}
    assert ev["user"]["id"] == "u1"
    assert ev["ecs"]["version"]


@pytest.mark.asyncio
async def test_user_name_from_username(session, lines):
    u = User(username="jane.doe", password_hash="x")
    session.add(u)
    await session.commit()
    await audit(session, "auth.login", user_id=u.id)
    await audit(session, "auth.login", user_id="nope")
    known, unknown = (json.loads(x) for x in lines())
    assert known["user"]["name"] == "jane.doe"
    assert "name" not in unknown["user"]


@pytest.mark.asyncio
async def test_detail_redacted_in_json(session, lines):
    await audit(session, "provider.update",
                detail={"client_secret": "S3CR3T", "password": "p",
                        "nested": {"token": "T0K3N"}})
    (raw,) = lines()
    assert "S3CR3T" not in raw and "T0K3N" not in raw
    detail = json.loads(raw)["styx"]["audit"]["detail"]
    assert detail["client_secret"] == "[redacted]"
    assert detail["password"] == "[redacted]"
    assert detail["nested"]["token"] == "[redacted]"


@pytest.mark.parametrize("action,category,etype,outcome", [
    ("auth.login", "authentication", "start", "success"),
    ("auth.logout", "authentication", "end", "success"),
    ("user.role_change", "iam", "change", "success"),
    ("group.create", "iam", "creation", "success"),
    ("provider.update", "configuration", "change", "success"),
    ("profile.delete", "process", "deletion", "success"),
    ("auth.login_locked", "authentication", "start", "failure"),
    ("auth.refresh_reuse", "authentication", "info", "failure"),
    ("auth.login_failed", "authentication", "start", "failure"),
    ("service.denied", "configuration", "change", "failure"),
])
@pytest.mark.asyncio
async def test_category_mapping(session, lines, action, category, etype, outcome):
    await audit(session, action)
    ev = json.loads(lines()[0])["event"]
    assert ev["category"] == [category]
    assert ev["type"] == [etype]
    assert ev["outcome"] == outcome


@pytest.mark.asyncio
async def test_null_fields_omitted(session, lines):
    await audit(session, "settings.update")
    ev = json.loads(lines()[0])
    assert "user" not in ev and "source" not in ev
    assert "styx" not in ev  # resource and detail were None
    assert "null" not in lines()[0]


def test_logger_does_not_propagate():
    assert logging.getLogger("styx.audit").propagate is False


def test_dlp_event_never_hashes_content():
    ev = dlp_event(direction="out", channel="file", user_name="jane.doe",
                   filename="secret plans.pdf", size=42, mime_type="application/pdf")
    assert "hash" not in ev.get("file", {})
    assert "file.hash" not in json.dumps(ev)
    assert ev["styx"]["dlp"]["filename_sha256"] == hashlib.sha256(
        b"secret plans.pdf").hexdigest()
    assert "secret plans.pdf" not in json.dumps(ev)
    assert ev["event"]["dataset"] == "styx.dlp"
    assert ev["file"] == {"size": 42, "mime_type": "application/pdf"}


@pytest.mark.parametrize("channel,direction", [("clipboard", "in"), ("file", "out")])
def test_dlp_event_keys_are_allowlisted(channel, direction):
    ev = dlp_event(direction=direction, channel=channel, filename="a.txt",
                   size=1, mime_type="text/plain", user_name="jane")
    assert set(ev) == {"@timestamp", "ecs", "event", "file", "user", "styx"}
    assert set(ev["file"]) == {"size", "mime_type"}
    assert set(ev["styx"]["dlp"]) == {"direction", "channel", "filename_sha256"}
    assert set(ev["user"]) == {"name"}


@pytest.mark.parametrize("action", ["allowed", "blocked"])
def test_egress_event_fields(action):
    ev = egress_event(domain="example.org", action=action, method="GET",
                      user_name="jane.doe", rule_category="news")
    assert ev["url"]["domain"] == "example.org"
    assert ev["destination"]["domain"] == "example.org"
    assert ev["event"]["action"] == action
    assert ev["event"]["dataset"] == "styx.egress"
    assert ev["http"]["request"]["method"] == "GET"


def test_egress_event_rejects_unknown_action():
    with pytest.raises(ValueError):
        egress_event(domain="example.org", action="maybe")
