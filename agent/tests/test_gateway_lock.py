"""Lock-overlay hook: selkies patch 04 applied to verbatim 2.2.0 excerpts, and the gateway sender."""
import asyncio
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))
import gateway_lock  # noqa: E402

PATCH = AGENT.parent / "patches/selkies/04-selkies-lock-overlay-hook.patch"
EXCERPT = Path(__file__).parent / "fixtures/selkies_ws_excerpt.py"
TOKEN = "s3cret-gateway-token"


@pytest.fixture
def wm(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("git missing")
    monkeypatch.setenv("STYX_LOCK_TOKEN", TOKEN)
    pkg = tmp_path / "selkies"
    pkg.mkdir()
    (pkg / "websockets_mode.py").write_text(EXCERPT.read_text())
    subprocess.run(["git", "apply", "--unsafe-paths", "-p1", "--directory", str(tmp_path),
                    str(PATCH)], check=True, cwd=tmp_path)
    spec = importlib.util.spec_from_file_location("wm_patched", pkg / "websockets_mode.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _frame(frame_id, ref, idr=False, payload=b"desktop"):
    head = bytes([0x04, 0x01 if idr else 0x00, frame_id >> 8, frame_id & 255, 0, 0,
                  0, 0, 0, 0, ref >> 8, ref & 255])
    return {"data": memoryview(head + payload), "frame_id": frame_id}


class _Group(SimpleNamespace):
    def join(self, relay): pass
    def hold(self, *a): pass


def _server():
    return SimpleNamespace(display_clients={}, _stream_watches={}, clients=set(),
                           video_relay_groups={}, common_frames_for=lambda d, h: _Group())


async def _drain(relay):
    task = asyncio.ensure_future(relay._run())
    await asyncio.sleep(0.05)
    relay.stopped = True
    relay._wake.set()
    await asyncio.wait_for(task, 1)


def _run_relay(wm, relay):
    asyncio.run(_drain(relay))
    return [d for _, d in wm.WRITES]


def test_locked_relay_writes_no_video(wm):
    wm.WRITES.clear()
    relay = wm._VideoRelay(_server(), "primary", "ws")
    relay.offer(_frame(1, 1, idr=True))  # queued before the lock
    wm.LOCK["locked"] = True
    for i in range(2, 5):
        relay.offer(_frame(i, i - 1))   # offered while locked
    assert _run_relay(wm, relay) == []  # nothing, not even the queued key frame
    assert not relay.backlog


def test_unlock_resumes_real_frames(wm):
    wm.WRITES.clear()
    relay = wm._VideoRelay(_server(), "primary", "ws")
    wm.LOCK["locked"] = True
    relay.offer(_frame(1, 1, idr=True))
    wm.LOCK["locked"] = False
    relay.offer(_frame(2, 2, idr=True, payload=b"real2"))
    out = _run_relay(wm, relay)
    assert len(out) == 1 and out[0].endswith(b"real2")


@pytest.mark.parametrize("msg,ok", [
    (f"STYX_LOCK,1,{TOKEN}", True), (f"STYX_LOCK,0,{TOKEN}", True),
    ("STYX_LOCK,1", False), ("STYX_LOCK,1,wrong", False), (f"STYX_LOCK,2,{TOKEN}", False),
    ("SET_FOO,1", None),
])
def test_handle_lock_command(wm, msg, ok):
    assert wm.handle_lock_command(msg) is ok


def test_lock_refused_without_configured_token(wm, monkeypatch):
    monkeypatch.delenv("STYX_LOCK_TOKEN")
    assert wm.handle_lock_command("STYX_LOCK,1,") is False
    assert not wm.LOCK["locked"]


def _msgs(*texts):
    return [SimpleNamespace(type="text", data=t) for t in texts]


def test_dispatch_applies_gateway_lock_and_requests_keyframe(wm):
    srv = wm.DataStreamingServer()
    asyncio.run(srv.ws_handler("gw", ("127.0.0.1", 1), _msgs(f"STYX_LOCK,1,{TOKEN}")))
    assert wm.LOCK["locked"] and srv.idr_requests == ["primary"]
    asyncio.run(srv.ws_handler("gw", ("127.0.0.1", 1), _msgs(f"STYX_LOCK,0,{TOKEN}")))
    assert not wm.LOCK["locked"]


def test_dispatch_still_reaches_other_messages(wm):
    srv = wm.DataStreamingServer()
    got = asyncio.run(srv.ws_handler("c", ("h", 1), _msgs("SETTINGS,{}")))
    assert got == ["SETTINGS,{}"]


@pytest.mark.parametrize("role", ["viewer", "controller"])
def test_viewer_or_controller_cannot_unlock(wm, role):
    srv = wm.DataStreamingServer()
    wm.LOCK["locked"] = True
    wm.client_permissions["page"] = {"role": role}
    asyncio.run(srv.ws_handler("page", ("9.9.9.9", 1), _msgs(
        "STYX_LOCK,0", "STYX_LOCK,0,", "STYX_LOCK,0,guess")))
    assert wm.LOCK["locked"] is True


class _WS:
    def __init__(self):
        self.out = []

    async def send_str(self, s):
        self.out.append(s)


def test_gateway_sends_lock_and_unlock():
    ws = _WS()
    asyncio.run(gateway_lock.send_lock(ws, True, TOKEN))
    asyncio.run(gateway_lock.send_lock(ws, False, TOKEN))
    assert ws.out == [f"STYX_LOCK,1,{TOKEN}", f"STYX_LOCK,0,{TOKEN}"]


def test_gateway_token_from_env_and_required(monkeypatch):
    ws = _WS()
    monkeypatch.setenv("STYX_LOCK_TOKEN", TOKEN)
    asyncio.run(gateway_lock.send_lock(ws, True))
    assert ws.out == [f"STYX_LOCK,1,{TOKEN}"]
    monkeypatch.delenv("STYX_LOCK_TOKEN")
    with pytest.raises(RuntimeError):
        asyncio.run(gateway_lock.send_lock(ws, True))
