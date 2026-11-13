import re
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


PATCH = Path(__file__).parents[2] / "patches" / "selkies" / "05-pixelflux-watermark.patch"

# Shared with the Rust test `matches_python_spec` in the patch: 520x60 frame
# filled with 0x40, stamped for "alice" at NOW. Keep the two in lock step.
SPEC_W, SPEC_H = 520, 60
SPEC_FNV = 0xAB44D549D35AA840
SPEC_PIXELS = {(15, 16): 64, (16, 16): 0, (25, 22): 255, (24, 22): 0,
               (492, 48): 0, (493, 48): 64, (16, 49): 64}


def fnv1a64(data):
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & (2**64 - 1)
    return h


def spec_frame():
    f = bytearray(b"\x40" * (SPEC_W * SPEC_H * 3))
    watermark.render(f, SPEC_W, SPEC_H, watermark.text_for("alice", NOW))
    return f


def test_spec_values_pinned_for_rust():
    f = spec_frame()
    assert fnv1a64(f) == SPEC_FNV
    for (x, y), v in SPEC_PIXELS.items():
        assert f[(y * SPEC_W + x) * 3] == v, (x, y)


def added(patch_text, path):
    """Added lines of one file's diff."""
    sec = patch_text.split(f"diff --git a/{path} ")[1].split("\ndiff --git ")[0]
    return [ln[1:] for ln in sec.splitlines() if ln.startswith("+") and not ln.startswith("+++")]


def test_patch_input_is_only_the_env_var():
    rs = "\n".join(added(PATCH.read_text(), "pixelflux/src/watermark.rs"))
    assert re.findall(r"env::var\(([^)]*)\)", rs) == ['"STYX_WATERMARK_USER"']
    assert "pyfunction" not in rs and "pymethods" not in rs
    # No mutators: every method takes &self (or nothing), no setters or statics.
    assert "&mut self" not in rs and "static mut" not in rs
    assert not re.search(r"fn (set|disable|enable|update)\w*", rs)


def test_patch_hooks_capture_loop_unconditionally():
    text = PATCH.read_text()
    lib = added(text, "pixelflux/src/lib.rs")
    assert "pub mod watermark;" in lib
    calls = [ln for ln in lib if "watermark::" in ln and "stamp" in ln or "stamp_bgra" in ln]
    assert len(calls) >= 2  # pool buffer and frame buffer
    # Not gated on a client-controlled setting (wm_active etc.).
    assert not any("wm_active" in ln or "settings" in ln for ln in lib)


def test_snapshot_matches_reference():
    f = make_frame()
    watermark.render(f, W, H, watermark.text_for("alice", NOW))
    ref, w, h = read_png(FIXTURE)
    assert (w, h) == (W, H)
    diff = sum(1 for i in range(0, len(f), 3) if f[i:i + 3] != ref[i:i + 3])
    assert diff <= TOL_PIXELS
