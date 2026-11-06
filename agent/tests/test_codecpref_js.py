"""Hardware-codec-first answer shim (CODECPREF_JS), run in node with fakes."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import codecpref  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node missing")

HARNESS = r"""
const assert = require('assert'), vm = require('vm');
const html = process.argv[process.argv.length - 1];
const body = html.slice(html.indexOf('>') + 1, html.lastIndexOf('</script>'));
const SDP = 'v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 45 46 49 102\r\n' +
  'a=rtpmap:45 AV1/90000\r\na=rtpmap:46 rtx/90000\r\na=rtpmap:49 H265/90000\r\na=rtpmap:102 H264/90000\r\n';
const CAPS = ['video/VP8', 'video/rtx', 'video/H264', 'video/AV1', 'video/H265'].map((m) => ({mimeType: m}));
async function run(hwSet, sdp, store = {}) {
  const prefs = [], posts = [], answered = [];
  function PC() {}
  PC.prototype.createAnswer = function () { answered.push(prefs.length); return Promise.resolve({type: 'answer'}) };
  PC.prototype.getTransceivers = function () {
    return [{receiver: {track: {kind: 'video'}}, setCodecPreferences: (c) => prefs.push(c.map((x) => x.mimeType))},
            {receiver: {track: {kind: 'audio'}}, setCodecPreferences: () => { throw new Error('audio touched') }}];
  };
  const win = {
    RTCPeerConnection: PC, Promise, RegExp, setTimeout,
    localStorage: {getItem: (k) => (k in store ? store[k] : null)},
    RTCRtpReceiver: {getCapabilities: () => ({codecs: CAPS})},
    navigator: {mediaCapabilities: {decodingInfo: (c) => Promise.resolve(
      {supported: true, powerEfficient: hwSet.includes(c.video.contentType)})}},
    fetch: (u, o) => { posts.push(JSON.parse(o.body)); return Promise.resolve() },
  };
  win.window = win;
  vm.createContext(win);
  vm.runInContext(body, win);
  const pc = new PC();
  pc.remoteDescription = {sdp};
  await pc.createAnswer();
  return {prefs, posts, answered};
}
(async () => {
  // HEVC in hardware, AV1 offered first: HEVC first, then the rest in offer order
  let r = await run(['video/h265'], SDP);
  assert.deepStrictEqual(r.prefs, [['video/H265', 'video/AV1', 'video/H264', 'video/VP8', 'video/rtx']]);
  assert.deepStrictEqual(r.answered, [1]);                       // reordered before the answer
  assert.deepStrictEqual(r.posts[0].diag.codecpref, ['video/h265', 'video/av1', 'video/h264']);
  // nothing in hardware: answer untouched
  r = await run([], SDP);
  assert.deepStrictEqual(r.prefs, []);
  assert.deepStrictEqual(r.answered, [0]);
  // AV1 in hardware and offered first: untouched
  r = await run(['video/av1', 'video/h265'], SDP);
  assert.deepStrictEqual(r.prefs, []);
  // no video m-line: untouched
  r = await run(['video/h265'], 'v=0\r\n');
  assert.deepStrictEqual(r.prefs, []);
  // a manual pick in the panel: the answer is the browser's, nothing reordered
  r = await run(['video/h265'], SDP, {styx_codec_manual: '1'});
  assert.deepStrictEqual(r.prefs, []);
  assert.deepStrictEqual(r.answered, [0]);
  console.log('ok');
})().catch((e) => { console.error(e); process.exit(1) });
"""


AUTO_HARNESS = r"""
const assert = require('assert'), vm = require('vm');
const html = process.argv[process.argv.length - 1];
const body = html.slice(html.indexOf('>') + 1, html.lastIndexOf('</script>'));
function storage(init) {
  const m = new Map(Object.entries(init));
  return {get length() { return m.size }, key: (i) => [...m.keys()][i],
          getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v),
          removeItem: (k) => m.delete(k), dump: () => Object.fromEntries(m)};
}
function boot(init) {
  const opts = ['av1enc', 'h265enc', 'h264enc'].map((v) => ({value: v, disabled: false}));
  const select = {
    id: 'encoderSelect', value: 'av1enc', options: opts, dispatched: [],
    querySelector: () => opts.find((o) => o.value === 'auto') || null,
    insertBefore: (o) => opts.unshift(o),
    dispatchEvent(e) { this.dispatched.push(this.value); handler({target: this, stopPropagation() {}}) },
  };
  let handler, tick, later, reloads = 0;
  const win = {
    localStorage: storage(init), Event: function (t) { this.type = t },
    document: {addEventListener: (t, f, cap) => { assert(cap); handler = f },
               getElementById: () => select,
               createElement: () => ({value: '', textContent: ''})},
    setInterval: (f) => { tick = f }, setTimeout: (f) => { later = f },
    location: {reload: () => { reloads++ }},
  };
  win.window = win;
  vm.createContext(win);
  vm.runInContext(body, win);
  return {win, select, opts, tick: () => tick(), change: (value) => {
    select.value = value; let stopped = false;
    handler({target: select, stopPropagation() { stopped = true }});
    return stopped;
  }, flush: () => later(), reloads: () => reloads};
}
// auto is the default: stored picks go before selkies reads them, others stay
let p = boot({selkies_encoder: 'av1enc', selkies_encoder_pick: 'x', selkies_encoder_display2: 'y',
              selkies_webcam_encoder: 'keep', selkies_framerate: '60'});
assert.deepStrictEqual(p.win.localStorage.dump(), {selkies_webcam_encoder: 'keep', selkies_framerate: '60'});
// the option appears once, on top, and stays selected through React resets
p.tick(); p.tick();
assert.deepStrictEqual(p.opts.map((o) => o.value), ['auto', 'av1enc', 'h265enc', 'h264enc']);
assert.strictEqual(p.select.value, 'auto');
p.select.value = 'h265enc'; p.tick();
assert.strictEqual(p.select.value, 'auto');
// a manual pick reaches React, is remembered, survives reload and is left alone
assert.strictEqual(p.change('h264enc'), false);
assert.strictEqual(p.win.localStorage.getItem('styx_codec_manual'), '1');
p.tick();
assert.strictEqual(p.select.value, 'h264enc');
p = boot({styx_codec_manual: '1', selkies_encoder: 'h264enc'});
assert.strictEqual(p.win.localStorage.getItem('selkies_encoder'), 'h264enc');
p.tick();
assert.strictEqual(p.select.value, 'av1enc');
// back to auto: hidden from React, server sent to the top codec, then fresh reload
p.tick();
p.win.localStorage.setItem('selkies_encoder', 'av1enc');
assert.strictEqual(p.change('auto'), true);
assert.deepStrictEqual(p.select.dispatched, ['av1enc']);
assert.strictEqual(p.win.localStorage.getItem('styx_codec_manual'), null);
assert.strictEqual(p.reloads(), 0);
p.flush();
assert.strictEqual(p.reloads(), 1);
assert.strictEqual(p.win.localStorage.getItem('selkies_encoder'), null);
// disabled codecs are never the auto target
p = boot({styx_codec_manual: '1'});
p.tick();
p.opts[1].disabled = true;
p.change('auto');
assert.deepStrictEqual(p.select.dispatched, ['h265enc']);
console.log('ok');
"""


def _script(html, tag_id):
    script = html[html.index(f'<script id="{tag_id}">'):]
    return script[:script.index("</script>") + len("</script>")]


def _node(harness, script):
    r = subprocess.run(["node", "-e", harness, script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr


def test_hardware_codec_first_in_answer():
    _node(HARNESS, _script(codecpref.inject_codecpref("<head></head>"), "styx-codecpref"))


def test_panel_auto_option():
    _node(AUTO_HARNESS, _script(codecpref.inject_codecpref("<head></head>"), "styx-codec-auto"))


def test_inject_needs_head():
    assert codecpref.inject_codecpref("<body></body>") == "<body></body>"
