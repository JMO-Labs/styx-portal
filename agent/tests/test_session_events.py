import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session_events as se  # noqa: E402
import styx_agent  # noqa: E402


def test_record_and_pending(tmp_path):
    p = tmp_path / "ev.jsonl"
    se.record(p, "connect", "v1")
    se.record(p, "disconnect", "v1")
    evs, n = se.pending(p)
    assert [(e["action"], e["viewer_id"]) for e in evs] == [("connect", "v1"), ("disconnect", "v1")]
    assert evs[0]["ts"].endswith("+00:00") or evs[0]["ts"].endswith("Z")
    assert n == 2


def test_bounded_oldest_dropped(tmp_path):
    p = tmp_path / "ev.jsonl"
    for i in range(130):
        se.record(p, "connect", f"v{i}")
    evs, _ = se.pending(p)
    assert len(evs) == 100
    assert evs[0]["viewer_id"] == "v30" and evs[-1]["viewer_id"] == "v129"


def test_ack_clears_only_sent(tmp_path):
    p = tmp_path / "ev.jsonl"
    se.record(p, "connect", "a")
    evs, n = se.pending(p)
    se.record(p, "disconnect", "a")      # arrives while heartbeat in flight
    se.ack(p, n)
    evs2, _ = se.pending(p)
    assert [e["action"] for e in evs2] == ["disconnect"]


def test_pending_missing_file(tmp_path):
    assert se.pending(tmp_path / "none") == ([], 0)


@pytest.mark.asyncio
async def test_gateway_attach_detach_records(tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    import base64
    import gateway

    async def upstream_ws(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for _ in ws:
            pass
        return ws

    upstream = web.Application()
    upstream.router.add_get("/api/websockets", upstream_ws)
    up = TestClient(TestServer(upstream))
    await up.start_server()
    app = gateway.create_app("styx", "pw", upstream_port=up.server.port,
                             state_file=str(tmp_path / "gw_state.json"))
    client = TestClient(TestServer(app))
    await client.start_server()
    auth = "Basic " + base64.b64encode(b"styx:pw").decode()
    try:
        ws = await client.ws_connect("/websocket", headers={"Authorization": auth})
        await ws.close()
        for _ in range(50):
            evs, _n = se.pending(tmp_path / se.NAME)
            if len(evs) == 2:
                break
            await asyncio.sleep(0.05)
    finally:
        await client.close()
        await up.close()
    assert [e["action"] for e in evs] == ["connect", "disconnect"]
    assert evs[0]["viewer_id"] == evs[1]["viewer_id"]


def test_heartbeat_sends_then_clears(tmp_path):
    p = tmp_path / "ev.jsonl"
    se.record(p, "connect", "a")
    body = {}
    with patch.object(styx_agent, "api", side_effect=lambda c, path, b: body.update(b) or {"state": "ok"}):
        hb = styx_agent.send_heartbeat({}, {"status": "online", "health": {}}, p)
    assert body["health"]["session_events"][0]["viewer_id"] == "a"
    assert hb == {"state": "ok"}
    assert se.pending(p) == ([], 0)


def test_failed_heartbeat_keeps_events(tmp_path):
    p = tmp_path / "ev.jsonl"
    se.record(p, "connect", "a")
    with patch.object(styx_agent, "api", side_effect=OSError("down")):
        try:
            styx_agent.send_heartbeat({}, {"status": "online", "health": {}}, p)
        except OSError:
            pass
    assert len(se.pending(p)[0]) == 1
