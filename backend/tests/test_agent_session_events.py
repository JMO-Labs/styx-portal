import json
import logging

import pytest
from sqlmodel import select

from app.models import User
from tests.test_workstation_agent_api import _auth, _make_ws


def _lines(caplog):
    out = []
    for r in caplog.records:
        if r.name == "styx.audit":
            ev = json.loads(r.getMessage())
            if ev["event"]["action"].startswith("session."):
                out.append(ev)
    return out


async def _hb(client, events):
    health = {} if events is None else {"session_events": events}
    return await client.post("/api/agent/heartbeat", json={"health": health}, headers=_auth())


@pytest.mark.asyncio
async def test_valid_events_emit_lines(client, session, caplog):
    ws = await _make_ws(session)
    owner = (await session.exec(select(User))).first()
    ws.occupied_by = owner.id
    session.add(ws)
    await session.commit()
    caplog.set_level(logging.INFO, logger="styx.audit")
    r = await _hb(client, [
        {"action": "connect", "viewer_id": "v1", "ts": "2026-11-01T10:00:00Z"},
        {"action": "disconnect", "viewer_id": "v1", "ts": "2026-11-01T10:05:00+00:00"}])
    assert r.status_code == 200
    evs = _lines(caplog)
    assert [e["event"]["action"] for e in evs] == ["session.connect", "session.disconnect"]
    e = evs[0]
    assert e["styx"]["session"] == {"id": ws.id, "kind": "workstation", "viewer_id": "v1"}
    assert e["@timestamp"] == "2026-11-01T10:00:00.000Z"
    assert e["host"]["name"] == "desk"
    assert e["user"]["id"] == owner.id and e["user"]["name"] == owner.username


@pytest.mark.asyncio
async def test_no_owner_omits_user(client, session, caplog):
    await _make_ws(session)
    caplog.set_level(logging.INFO, logger="styx.audit")
    await _hb(client, [{"action": "connect", "viewer_id": "v", "ts": "2026-11-01T10:00:00Z"}])
    assert "user" not in _lines(caplog)[0]


@pytest.mark.asyncio
async def test_invalid_records_skipped(client, session, caplog):
    await _make_ws(session)
    caplog.set_level(logging.INFO, logger="styx.audit")
    ok = {"action": "connect", "viewer_id": "v", "ts": "2026-11-01T10:00:00Z"}
    r = await _hb(client, ["x", 3, None,
                           {"action": "launch", "viewer_id": "v", "ts": ok["ts"]},
                           {"action": "connect", "viewer_id": "v", "ts": "nope"},
                           {"action": "connect", "viewer_id": "v", "ts": 5},
                           {"action": "connect", "viewer_id": 7, "ts": ok["ts"]},
                           ok])
    assert r.status_code == 200 and r.json()["state"] == "ok"
    assert len(_lines(caplog)) == 1


@pytest.mark.asyncio
async def test_capped_at_100(client, session, caplog):
    await _make_ws(session)
    caplog.set_level(logging.INFO, logger="styx.audit")
    rec = {"action": "connect", "viewer_id": "v", "ts": "2026-11-01T10:00:00Z"}
    assert (await _hb(client, [rec] * 130)).status_code == 200
    assert len(_lines(caplog)) == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("val", [None, "junk", {"a": 1}])
async def test_missing_or_malformed_list(client, session, caplog, val):
    await _make_ws(session)
    caplog.set_level(logging.INFO, logger="styx.audit")
    r = await _hb(client, val)
    assert r.status_code == 200 and r.json()["state"] == "ok"
    assert _lines(caplog) == []
