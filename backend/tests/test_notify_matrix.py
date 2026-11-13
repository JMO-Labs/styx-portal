import json

import httpx
import pytest

from app.config import Settings
from app.services import notify_matrix as nm

CFG = Settings(MATRIX_NOTIFY_HOMESERVER="https://hs.test/", MATRIX_NOTIFY_ROOM_ID="!r:hs.test",
               MATRIX_NOTIFY_TOKEN="s3cret-token")


async def test_send_success():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["req"] = req
        return httpx.Response(200, json={"event_id": "$e"})

    assert await nm.send("hello", CFG, transport=httpx.MockTransport(handler)) is True
    r = seen["req"]
    assert r.method == "PUT"
    assert r.url.raw_path.startswith(
        b"/_matrix/client/v3/rooms/%21r%3Ahs.test/send/m.room.message/")
    assert r.headers["authorization"] == "Bearer s3cret-token"
    assert json.loads(r.content) == {"msgtype": "m.text", "body": "hello"}


async def test_send_http_error_returns_false_without_leaking_token(caplog):
    t = httpx.MockTransport(lambda r: httpx.Response(403, json={"errcode": "M_FORBIDDEN"}))
    assert await nm.send("x", CFG, transport=t) is False
    assert "s3cret-token" not in caplog.text


async def test_send_transport_error_returns_false():
    def boom(req):
        raise httpx.ConnectError("down")

    assert await nm.send("x", CFG, transport=httpx.MockTransport(boom)) is False


@pytest.mark.parametrize("field", ["MATRIX_NOTIFY_HOMESERVER", "MATRIX_NOTIFY_ROOM_ID",
                                   "MATRIX_NOTIFY_TOKEN"])
async def test_disabled_makes_no_call(field):
    cfg = CFG.model_copy(update={field: ""})
    calls = []
    t = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200))
    assert nm.configured(cfg) is False
    assert await nm.send("x", cfg, transport=t) is False
    assert calls == []
