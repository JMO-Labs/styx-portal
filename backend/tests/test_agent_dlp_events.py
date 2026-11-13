"""POST /api/agent/dlp-events: metadata-only DLP events -> ECS (styx-portal#230)."""
import io
import json
import logging

import pytest
from sqlmodel import select

from app.models import User
from tests.test_workstation_agent_api import _auth, _make_ws

ALLOWED = {"@timestamp", "ecs", "event", "file", "user", "styx"}
URL = "/api/agent/dlp-events"
EV = {"direction": "out", "channel": "file", "size": 12,
      "mime_type": "text/plain", "filename": "secret-plans.pdf",
      "ts": "2026-11-13T10:00:00Z"}


@pytest.fixture
def lines():
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("styx.audit")
    log.addHandler(h)
    yield lambda: [json.loads(x) for x in buf.getvalue().splitlines() if x]
    log.removeHandler(h)


@pytest.mark.asyncio
async def test_requires_agent_token(client, session):
    await _make_ws(session)
    assert (await client.post(URL, json=[EV])).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["content", "text", "data"])
async def test_extra_fields_rejected(client, session, lines, field):
    await _make_ws(session)
    r = await client.post(URL, json=[{**EV, field: "TOP-SECRET"}], headers=_auth())
    assert r.status_code == 422
    assert lines() == []


@pytest.mark.asyncio
async def test_user_name_from_owner_not_request(client, session, lines):
    ws = await _make_ws(session)
    owner = await session.get(User, ws.created_by)
    r = await client.post(URL, json=[EV, {**EV, "channel": "clipboard", "direction": "in"}],
                          headers=_auth())
    assert r.status_code == 200
    out = lines()
    assert len(out) == 2
    assert {e["user"]["name"] for e in out} == {owner.username}
    assert out[0]["@timestamp"].startswith("2026-11-13T10:00:00")


@pytest.mark.asyncio
async def test_user_name_in_request_rejected(client, session):
    await _make_ws(session)
    r = await client.post(URL, json=[{**EV, "user_name": "mallory"}], headers=_auth())
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_no_content_in_emitted_lines(client, session, lines):
    await _make_ws(session)
    r = await client.post(URL, json=[EV], headers=_auth())
    assert r.status_code == 200
    raw = json.dumps(lines())
    for ev in lines():
        assert set(ev) <= ALLOWED
        assert set(ev["styx"]["dlp"]) <= {"direction", "channel", "filename_sha256"}
    assert "secret-plans.pdf" not in raw


@pytest.mark.asyncio
async def test_invalid_direction_422(client, session):
    await _make_ws(session)
    r = await client.post(URL, json=[{**EV, "direction": "sideways"}], headers=_auth())
    assert r.status_code == 422
