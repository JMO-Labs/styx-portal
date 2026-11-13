import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path

from agent import watermark

FIXTURE = Path(__file__).parent / "fixtures" / "watermark-1080p.png"
W, H = 1920, 1080
NOW = datetime(2026, 11, 13, 9, 5, 7, tzinfo=timezone.utc)
TOL_PIXELS = 20  # max differing pixels (of 2M)


def make_frame():
    f = bytearray(W * H * 3)
    for y in range(H):
        row = bytes([40 + y * 60 // H, 60, 90]) * W
        f[y * W * 3:(y + 1) * W * 3] = row
    return f


def write_png(path, rgb, w, h):
    raw = b"".join(b"\0" + bytes(rgb[y * w * 3:(y + 1) * w * 3]) for y in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d))

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def read_png(path):
    b = path.read_bytes()
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(b):
        n, t = struct.unpack(">I4s", b[pos:pos + 8])
        d = b[pos + 8:pos + 8 + n]
        if t == b"IHDR":
            w, h = struct.unpack(">II", d[:8])
        elif t == b"IDAT":
            idat += d
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = w * 3 + 1
    out = bytearray()
    for y in range(h):
        assert raw[y * stride] == 0
        out += raw[y * stride + 1:(y + 1) * stride]
    return out, w, h


def test_text_has_user_and_utc_time():
    assert watermark.text_for("alice", NOW) == "ALICE 2026-11-13 09:05:07Z"


def test_text_converts_to_utc():
    from datetime import timedelta
    tz = timezone(timedelta(hours=2))
    assert watermark.text_for("a", NOW.astimezone(tz)).endswith("09:05:07Z")


def test_user_comes_from_env_only():
    assert watermark.from_env({"STYX_WATERMARK_USER": " bob "}) == "bob"
    assert watermark.from_env({}) == ""


def test_client_message_cannot_change_or_disable():
    wm = watermark.Watermark.from_env({"STYX_WATERMARK_USER": "bob"})
    before = wm.text(NOW)
    for msg in ('SETTINGS,{"watermark":false,"STYX_WATERMARK_USER":"eve"}',
                {"watermark": "off", "user": "eve"}, b"\x00", None):
        wm.on_client_message(msg)
    assert wm.text(NOW) == before == "BOB 2026-11-13 09:05:07Z"
    f = make_frame()
    g = make_frame()
    watermark.render(f, W, H, before)
    assert f != g


def test_snapshot_matches_reference():
    f = make_frame()
    watermark.render(f, W, H, watermark.text_for("alice", NOW))
    ref, w, h = read_png(FIXTURE)
    assert (w, h) == (W, H)
    diff = sum(1 for i in range(0, len(f), 3) if f[i:i + 3] != ref[i:i + 3])
    assert diff <= TOL_PIXELS
