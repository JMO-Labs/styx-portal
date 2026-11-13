"""Lock-overlay hook: selkies patch 04 (applied to a stub) and the gateway sender."""
import asyncio
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))
import gateway_lock  # noqa: E402

PATCH = AGENT.parent / "patches/selkies/04-selkies-lock-overlay-hook.patch"
STUB = Path(__file__).parent / "fixtures/websockets_mode_stub.py"


@pytest.fixture
def wm(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git missing")
    pkg = tmp_path / "selkies"
    pkg.mkdir()
    (pkg / "websockets_mode.py").write_text(STUB.read_text())
    subprocess.run(["git", "apply", "--unsafe-paths", "-p1", "--directory", str(tmp_path),
                    str(PATCH)], check=True, cwd=tmp_path)
    spec = importlib.util.spec_from_file_location("wm_patched", pkg / "websockets_mode.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Srv:
    def _owns_display(self, ws, d):
        return True


def test_locked_relay_yields_only_blank_frames(wm):
    relay = wm._VideoRelay(_Srv(), object())
    assert relay._forward(1, b"real1") and relay.sent == [b"real1"]
    wm.set_lock(True)
    for i in range(3):
        relay._forward(2 + i, b"desktop")
    assert relay.sent == [b"real1"] + [wm.BLANK_FRAME] * 3
    assert b"desktop" not in relay.sent


def test_unlock_resumes_real_frames(wm):
    relay = wm._VideoRelay(_Srv(), object())
    wm.set_lock(True)
    relay._forward(1, b"x")
    wm.set_lock(False)
    relay._forward(2, b"real2")
    assert relay.sent[-1] == b"real2"


def test_control_command_toggles_lock(wm):
    assert wm.handle_lock_command("STYX_LOCK,1") is True and wm.LOCK["locked"]
    assert wm.handle_lock_command("STYX_LOCK,0") is True and not wm.LOCK["locked"]
    assert wm.handle_lock_command("SET_FOO,1") is False


class _WS:
    def __init__(self):
        self.out = []

    async def send_str(self, s):
        self.out.append(s)


def test_gateway_sends_lock_and_unlock():
    ws = _WS()
    asyncio.run(gateway_lock.send_lock(ws, True))
    asyncio.run(gateway_lock.send_lock(ws, False))
    assert ws.out == ["STYX_LOCK,1", "STYX_LOCK,0"]
