"""Gateway DLP filter: clipboard/file messages dropped per policy, both ways."""
import asyncio
import gzip
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gateway_dlp import allow_message  # noqa: E402

ALL_ON = dict(clipboard_in=True, clipboard_out=True, upload=True, download=True)


def pol(**kw):
    return {**ALL_ON, **kw}


@pytest.mark.parametrize("msg", ["cw,aGk=", "cws,text/plain,10", "cwd,aGk=", "cwe",
                                 "cb,aGk=", "cbs,image/png,9", "cbd,xx", "cbe"])
def test_clipboard_in_dropped_when_off(msg):
    assert not allow_message(msg, "in", pol(clipboard_in=False))
    assert allow_message(msg, "in", pol(clipboard_in=True))
    assert allow_message(msg, "in", pol(clipboard_out=False))


@pytest.mark.parametrize("msg", ["clipboard,aGk=", "clipboard_binary,image/png,xx",
                                 "clipboard_start,text/plain,9", "clipboard_data,xx",
                                 "clipboard_finish", "clipboard_reply,cr", "clipboard_secret"])
def test_clipboard_out_dropped_when_off(msg):
    assert not allow_message(msg, "out", pol(clipboard_out=False))
    assert allow_message(msg, "out", pol(clipboard_out=True))
    assert allow_message(msg, "out", pol(clipboard_in=False))


@pytest.mark.parametrize("msg", ["cr", "REQUEST_CLIPBOARD"])
def test_clipboard_read_request_follows_clipboard_out(msg):
    assert not allow_message(msg, "in", pol(clipboard_out=False))
    assert allow_message(msg, "in", pol(clipboard_out=True, clipboard_in=False))


def test_upload_in_dropped_when_off():
    for m in ("FILE_UPLOAD_START:a.txt:5", "FILE_UPLOAD_END:a.txt", b"\x01chunk"):
        assert not allow_message(m, "in", pol(upload=False))
        assert allow_message(m, "in", pol(upload=True))


def test_download_out_dropped_when_off():
    for m in ("FILE_DOWNLOAD_START:a.txt:5", "FILE_DOWNLOAD_END:a.txt"):
        assert not allow_message(m, "out", pol(download=False))
        assert allow_message(m, "out", pol(download=True))


def test_outbound_audio_binary_not_mistaken_for_file_chunk():
    assert allow_message(b"\x01\x00opus", "out", pol(upload=False, download=False))


def test_gzip_wrapped_clipboard_is_inspected():
    wrapped = b"\x05" + gzip.compress(b"cw,aGk=")
    assert not allow_message(wrapped, "in", pol(clipboard_in=False))
    assert allow_message(wrapped, "in", pol(clipboard_in=True))
    out = b"\x05" + gzip.compress(b"clipboard,aGk=")
    assert not allow_message(out, "out", pol(clipboard_out=False))


def test_undecodable_gzip_frame_dropped():
    assert not allow_message(b"\x05notgzip", "in", pol())


def test_missing_policy_uses_d38_defaults():
    assert allow_message("cw,x", "in", None)
    assert allow_message("clipboard,x", "out", {})
    assert allow_message("FILE_UPLOAD_START:a:1", "in", None)
    assert not allow_message("FILE_DOWNLOAD_START:a:1", "out", None)
    assert not allow_message("FILE_DOWNLOAD_START:a:1", "out", {"upload": False})


def test_other_messages_pass():
    for m in ("m2,1,2,0,0", "kd,65", "SETTINGS,{}", "_f,60", "pong", "clipboardx"):
        assert allow_message(m, "in", pol(clipboard_in=False, upload=False))
        assert allow_message(m, "out", pol(clipboard_out=False, download=False))
    assert allow_message(b"\x04video", "out", pol(download=False))


async def _relay(msgs, direction, policy):
    import gateway_ws
    import aiohttp

    class Src:
        def __init__(self, items):
            self.items = items

        def __aiter__(self):
            self.it = iter(self.items)
            return self

        async def __anext__(self):
            try:
                return next(self.it)
            except StopIteration:
                raise StopAsyncIteration

    class Dst:
        def __init__(self):
            self.sent = []

        async def send_str(self, d):
            self.sent.append(d)

        async def send_bytes(self, d):
            self.sent.append(d)

        async def close(self):
            pass

    M = type("M", (), {})

    def mk(t, d):
        m = M()
        m.type, m.data = t, d
        return m
    items = [mk(aiohttp.WSMsgType.BINARY if isinstance(d, bytes) else aiohttp.WSMsgType.TEXT, d)
             for d in msgs]
    dst = Dst()
    await gateway_ws.pump(Src(items), dst, direction=direction, policy=policy)
    return dst.sent


def test_pump_filters_both_directions_and_passes_rest():
    pytest.importorskip("aiohttp")
    p = {"clipboard_in": False, "clipboard_out": False, "upload": False}
    sent = asyncio.run(_relay(["cw,x", "m2,1,2", b"\x01c", b"\x04v"], "in", p))
    assert sent == ["m2,1,2", b"\x04v"]
    sent = asyncio.run(_relay(["clipboard,x", "FILE_DOWNLOAD_START:a:1", "ok", b"\x01a"], "out", p))
    assert sent == ["ok", b"\x01a"]


def test_pump_without_direction_is_unfiltered():
    pytest.importorskip("aiohttp")
    sent = asyncio.run(_relay(["cw,x"], None, {"clipboard_in": False}))
    assert sent == ["cw,x"]


@pytest.mark.asyncio
async def test_live_gateway_relay_drops_cw_in_and_clipboard_out():
    import base64
    gateway = pytest.importorskip("gateway")
    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    got = []

    async def upstream_ws(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str("clipboard,aGk=")
        await ws.send_str("hello")
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                got.append(msg.data)
        return ws

    up = web.Application()
    up.router.add_get("/api/websockets", upstream_ws)
    upc = TestClient(TestServer(up))
    await upc.start_server()
    app = gateway.create_app("styx", "pw", upstream_port=upc.server.port,
                              dlp_policy={"clipboard_in": False, "clipboard_out": False})
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        auth = "Basic " + base64.b64encode(b"styx:pw").decode()
        ws = await client.ws_connect("/websocket", headers={"Authorization": auth})
        await ws.send_str("cw,aGk=")
        await ws.send_str("m2,1,2")
        recv = [(await asyncio.wait_for(ws.receive(), 2)).data]
        await asyncio.sleep(0.2)
        await ws.close()
        assert recv == ["hello"]
        assert got == ["m2,1,2"]
    finally:
        await client.close()
        await upc.close()
