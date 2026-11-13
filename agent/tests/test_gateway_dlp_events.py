"""Gateway DLP transfer metadata: no content, batched, never blocks the relay."""
import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gateway_dlp import DlpReporter, event_meta  # noqa: E402

KEYS = {"direction", "channel", "size", "mime_type", "filename"}


def test_clipboard_text_meta():
    m = event_meta("cw," + base64.b64encode(b"hunter2").decode(), "in")
    assert set(m) == KEYS
    assert (m["direction"], m["channel"]) == ("in", "clipboard")
    assert m["size"] == len("cw," + base64.b64encode(b"hunter2").decode())
    assert m["filename"] is None


def test_clipboard_binary_mime():
    m = event_meta("cbs,image/png,9", "in")
    assert m["mime_type"] == "image/png" and m["channel"] == "clipboard"


def test_file_meta():
    m = event_meta("FILE_UPLOAD_START:report.pdf:2048", "in")
    assert m["channel"] == "file" and m["filename"] == "report.pdf"
    assert event_meta("FILE_DOWNLOAD_START:a.txt:5", "out")["direction"] == "out"


def test_file_chunk_binary_size_only():
    m = event_meta(b"\x01" + b"x" * 99, "in")
    assert m["channel"] == "file" and m["size"] == 100
    assert m["filename"] is None and m["mime_type"] is None


def test_non_transfer_is_none():
    assert event_meta("m,10,20", "in") is None
    assert event_meta(b"\x01audio", "out") is None
    assert event_meta(b"", "in") is None


def test_reporter_batches_and_never_leaks_content():
    async def run():
        posted = []
        r = DlpReporter(lambda evs: posted.append(evs), interval=0.05)
        secret = "cw," + base64.b64encode(b"TOPSECRET").decode()
        for _ in range(3):
            r.record(secret, "in", True)
        r.record(b"\x01" + b"FILEBYTES", "in", False)
        assert posted == []          # not synchronous
        await asyncio.sleep(0.2)
        return posted

    posted = asyncio.run(run())
    assert len(posted) == 1 and len(posted[0]) == 4
    blob = repr(posted)
    assert "TOPSECRET" not in blob and "FILEBYTES" not in blob
    assert "VE9QU0VDUkVU" not in blob
    assert posted[0][3]["allowed"] is False
    assert set(posted[0][0]) == KEYS | {"allowed"}


def test_reporter_failure_dropped_and_continues():
    async def run():
        calls, logs = [], []

        def bad(evs):
            calls.append(evs)
            raise OSError("down")

        r = DlpReporter(bad, interval=0.02, log=logs.append)
        r.record("cw,x", "in", True)
        await asyncio.sleep(0.1)
        r.record("cw,y", "in", True)
        await asyncio.sleep(0.1)
        return calls, logs

    calls, logs = asyncio.run(run())
    assert len(calls) == 2 and len(calls[1]) == 1   # first batch dropped, not retried
    assert logs


def test_reporter_ignores_non_transfers():
    async def run():
        posted = []
        r = DlpReporter(posted.append, interval=0.02)
        r.record("m,1,2", "in", True)
        await asyncio.sleep(0.08)
        return posted

    assert asyncio.run(run()) == []


def test_base64_clipboard_never_becomes_mime():
    b64 = base64.b64encode(b"\xff\xff\xff").decode()          # "////"
    for msg in ("cw," + b64, "clipboard," + b64, "cb,aGk/Pz8="):
        m = event_meta(msg, "in")
        assert m["mime_type"] is None
        assert b64 not in repr(m)


def test_mime_must_be_strict():
    assert event_meta("cbs,text/plain;x=1,9", "in")["mime_type"] is None
    assert event_meta("clipboard_start,image/png,9", "out")["mime_type"] == "image/png"
    assert event_meta("cbs,a/" + "b" * 200 + ",9", "in")["mime_type"] is None


def test_record_without_loop_or_failure_never_raises():
    r = DlpReporter(lambda e: None)
    r.record("cw,x", "in", True)            # no running loop
    r._buf = None                           # broken state
    r.record("cw,x", "in", True)


def test_flush_task_is_referenced():
    async def run():
        r = DlpReporter(lambda e: None, interval=0.01)
        r.record("cw,x", "in", True)
        await asyncio.sleep(0.05)
        return r._task is not None
    assert asyncio.run(run())


def test_build_reporter_from_config(tmp_path):
    import json
    from gateway_report import build_reporter
    assert build_reporter(str(tmp_path / "missing.json")) is None
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"server": "http://x", "agent_token": "t"}))
    assert build_reporter(str(p)) is not None


def test_pump_forwards_when_reporter_fails():
    from gateway_ws import pump

    class Msg:
        type = __import__("aiohttp").WSMsgType.TEXT
        data = "cw,hi"

    class Src:
        def __aiter__(self):
            async def g():
                yield Msg()
            return g()

    class Dst:
        sent = []

        async def send_str(self, s):
            self.sent.append(s)

        async def send_bytes(self, b):
            self.sent.append(b)

        async def close(self):
            pass

    class Rep:
        calls = 0

        def record(self, *a):
            Rep.calls += 1
            raise RuntimeError("boom")

    dst = Dst()
    asyncio.run(pump(Src(), dst, "in", None, Rep()))
    assert Rep.calls == 1 and dst.sent == ["cw,hi"]
