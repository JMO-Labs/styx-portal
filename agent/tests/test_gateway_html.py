"""RTT shim injection (postMessage to the portal page) and image-file parity."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import gateway_html  # noqa: E402

IMAGE_JS = ROOT.parent / "images/desktop/root/defaults/styx-rtt.js"


def test_rtt_shim_injected():
    html = gateway_html.inject_webrtc("<head></head>", True)
    assert 'id="styx-rtt"' in html
    shim = html[html.index('<script id="styx-rtt">'):html.index("</head>")]
    assert "styx-rtt" in shim and "postMessage" in shim
    assert "location.origin" in shim
    assert '"*"' not in shim and "'*'" not in shim
    assert "currentRoundTripTime" in shim and "rtt_ms" in shim


def test_rtt_shim_matches_image_file():
    assert IMAGE_JS.read_text().strip() in gateway_html.RTT_JS


HARNESS = r"""
const assert = require('assert'), vm = require('vm');
const body = process.argv[process.argv.length - 1];
const sent = []; let tick;
class PC { getStats() { return Promise.resolve(new Map([
  ['t', {id: 't', type: 'transport', selectedCandidatePairId: 'p'}],
  ['p', {id: 'p', type: 'candidate-pair', currentRoundTripTime: 0.042}]])) } }
const parent = {postMessage: (m, o) => sent.push([m, o])};
const win = {RTCPeerConnection: PC, parent, location: {origin: 'https://h'},
  document: {visibilityState: 'visible'}, setInterval: (f, ms) => { assert.strictEqual(ms, 5000); tick = f }};
win.window = win; win.document = win.document;
vm.runInNewContext(body, Object.assign(win, {document: win.document}));
const pc = new win.RTCPeerConnection();
tick();
setTimeout(() => {
  assert.strictEqual(JSON.stringify(sent[0]), JSON.stringify([{type: 'styx-rtt', rtt_ms: 42, transport: 'webrtc'}, 'https://h']));
  win.document.visibilityState = 'hidden'; tick();
  setTimeout(() => { assert.strictEqual(sent.length, 1); console.log('ok') }, 10);
}, 10);
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node missing")
def test_rtt_shim_posts_webrtc_rtt_to_own_origin():
    body = IMAGE_JS.read_text()
    r = subprocess.run(["node", "-e", HARNESS, body], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr
