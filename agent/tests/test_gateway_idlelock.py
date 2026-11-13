"""Idle lock mode: lock instead of close, signed unlock token (ADR-0039)."""
import asyncio
import hashlib
import hmac
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
gateway = pytest.importorskip("gateway")
aiohttp = pytest.importorskip("aiohttp")
from .test_gateway import _basic  # noqa: E402
from .test_gateway_busy import _closed_with, _pair  # noqa: E402
from .test_gateway_owner import _vid_ws  # noqa: E402

HDR = {"Authorization": _basic("styx", "pw")}
KEY, IID = "k3y", "inst-1"
LOCK = dict(lock_idle_s=1, unlock_key=KEY, unlock_url="https://portal/unlock",
            instance_id=IID)


@pytest.fixture(autouse=True)
def _no_connect_quiet(monkeypatch):
    monkeypatch.setattr(gateway, "CONNECT_QUIET_S", 0)


def _tok(iid=IID, exp=None, key=KEY):
    exp = int(time.time()) + 30 if exp is None else exp
    sig = hmac.new(key.encode(), f"{iid}.{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{iid}.{exp}.{sig}"


async def _locked(client):
    ws = await _vid_ws(client, "A", HDR)
    await _closed_with(ws, 4003, t=4, reason=b"locked")


@pytest.mark.asyncio
async def test_locks_after_idle_and_closes_sockets():
    up, client = await _pair(**LOCK)
    try:
        await _locked(client)
        st = await (await client.get("/styx/state", headers=HDR)).json()
        assert st["locked"] is True and st["locked_at"] is not None
    finally:
        await client.close(); await up.close()


@pytest.mark.asyncio
async def test_off_by_default_never_locks():
    up, client = await _pair()
    try:
        ws = await _vid_ws(client, "A", HDR)
        await asyncio.sleep(1.3)
        assert not ws.closed
        st = await (await client.get("/styx/state", headers=HDR)).json()
        assert st["locked"] is False and st["locked_at"] is None
        assert st["active_connections"] == 1
    finally:
        await client.close(); await up.close()


@pytest.mark.asyncio
async def test_423_while_locked_and_overlay_page():
    up, client = await _pair(**LOCK)
    try:
        await _locked(client)
        r = await client.get("/api/websockets", headers={**HDR, "Upgrade": "websocket"})
        assert r.status == 423
        r = await client.get("/", headers={**HDR, "Accept": "text/html"})
        body = await r.text()
        assert r.status == 423
        assert 'href="https://portal/unlock"' in body and "Unlock" in body
        assert r.headers["Content-Type"].startswith("text/html")
    finally:
        await client.close(); await up.close()


@pytest.mark.asyncio
async def test_valid_token_unlocks_and_redirects():
    up, client = await _pair(**LOCK)
    try:
        await _locked(client)
        r = await client.get(f"/styx/unlock?token={_tok()}", headers=HDR,
                             allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/"
        st = await (await client.get("/styx/state", headers=HDR)).json()
        assert st["locked"] is False
    finally:
        await client.close(); await up.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("make", [
    lambda: _tok(exp=int(time.time()) - 5),            # expired
    lambda: _tok(exp=int(time.time()) + 3600),         # beyond 60 s max
    lambda: _tok(key="wrong"),                         # forged
    lambda: _tok(iid="other"),                         # wrong instance
    lambda: "garbage",
    lambda: f"{IID}.\u00b2.ab",                        # non-ASCII digit
])
async def test_bad_token_403_stays_locked(make):
    up, client = await _pair(**LOCK)
    try:
        await _locked(client)
        r = await client.get(f"/styx/unlock?token={make()}", headers=HDR,
                             allow_redirects=False)
        assert r.status == 403
        st = await (await client.get("/styx/state", headers=HDR)).json()
        assert st["locked"] is True
    finally:
        await client.close(); await up.close()


@pytest.mark.asyncio
async def test_state_tracks_connections_and_disconnect():
    up, client = await _pair()
    try:
        ws = await _vid_ws(client, "A", HDR)
        st = await (await client.get("/styx/state", headers=HDR)).json()
        assert st["active_connections"] == 1 and st["last_disconnect_ts"] is None
        await ws.close()
        await asyncio.sleep(0.2)
        st = await (await client.get("/styx/state", headers=HDR)).json()
        assert st["active_connections"] == 0 and st["last_disconnect_ts"] is not None
    finally:
        await client.close(); await up.close()


async def _rtc_pair(tmp_path):
    from .test_gateway_webrtc import _pair as rtc_pair
    return await rtc_pair(tmp_path, **LOCK)


@pytest.mark.asyncio
async def test_webrtc_only_session_locks_and_drops_peer(tmp_path):
    from .test_gateway_webrtc import _sig
    up, client, _ = await _rtc_pair(tmp_path)
    try:
        ws = await _sig(client, "wr1")
        await _closed_with(ws, 4003, t=4, reason=b"locked")
        st = await (await client.get("/styx/state", headers=HDR)).json()
        assert st["locked"] is True
        assert (tmp_path / "gw_state.json.kill").read_text() == "locked"
        assert st["last_disconnect_ts"] is not None
    finally:
        await client.close(); await up.close()


@pytest.mark.asyncio
async def test_webrtc_activity_defers_lock(tmp_path):
    from .test_gateway_webrtc import _beacon, _sig
    up, client, _ = await _rtc_pair(tmp_path)
    try:
        ws = await _sig(client, "wr1")
        for _i in range(3):
            await asyncio.sleep(0.5)
            await _beacon(client, "wr1")
        assert not ws.closed
        st = await (await client.get("/styx/state", headers=HDR)).json()
        assert st["locked"] is False
    finally:
        await client.close(); await up.close()


@pytest.mark.asyncio
async def test_webrtc_close_stamps_last_disconnect(tmp_path):
    from .test_gateway_webrtc import _sig
    up, client, _ = await _pair_rtc_off(tmp_path)
    try:
        ws = await _sig(client, "wr1")
        await ws.close()
        await asyncio.sleep(0.2)
        st = await (await client.get("/styx/state", headers=HDR)).json()
        assert st["active_connections"] == 0 and st["last_disconnect_ts"] is not None
    finally:
        await client.close(); await up.close()


async def _pair_rtc_off(tmp_path):
    from .test_gateway_webrtc import _pair as rtc_pair
    return await rtc_pair(tmp_path)


@pytest.mark.asyncio
async def test_passive_viewer_does_not_lock_active_controller():
    up, client = await _pair(**LOCK)
    try:
        ctl = await _vid_ws(client, "A", HDR)
        viewer = await _vid_ws(client, "B", HDR, role="viewer")
        for _i in range(5):
            await asyncio.sleep(0.4)
            await ctl.send_str("kd,65")
        assert not ctl.closed and not viewer.closed
        st = await (await client.get("/styx/state", headers=HDR)).json()
        assert st["locked"] is False
    finally:
        await client.close(); await up.close()


@pytest.mark.asyncio
async def test_only_unlock_and_state_exempt_while_locked():
    up, client = await _pair(**LOCK)
    try:
        await _locked(client)
        for path in ("/styx/refit", "/styx/activity", "/styx/gamemode"):
            r = await client.post(path, headers=HDR)
            assert r.status == 423, path
        assert (await client.get("/styx/state", headers=HDR)).status == 200
    finally:
        await client.close(); await up.close()
