"""D38 audit hook (patches/selkies/03-selkies-audit-hook.patch): metadata only."""
import hashlib
import json
import logging
import re
import types
from pathlib import Path

PATCH = Path(__file__).resolve().parents[2] / "patches/selkies/03-selkies-audit-hook.patch"
FIELDS = {"user", "time", "direction", "size", "type", "filename_hash"}


def _load():
    """Build the module the patch adds (selkies/styx_audit.py) from its '+' lines."""
    text = PATCH.read_text()
    m = re.search(r"^\+\+\+ b/selkies/styx_audit\.py\n@@[^\n]*\n(.*?)(?=^--- |\Z)", text, re.S | re.M)
    src = "".join(ln[1:] + "\n" for ln in m.group(1).splitlines() if ln.startswith("+"))
    mod = types.ModuleType("styx_audit")
    exec(compile(src, "styx_audit.py", "exec"), mod.__dict__)
    return mod


def _capture(mod):
    lines = []

    class H(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    mod.log.addHandler(H())
    return lines


def test_clipboard_in_has_exactly_d38_fields(monkeypatch):
    monkeypatch.setenv("STYX_AUDIT_USER", "alice")
    mod = _load()
    lines = _capture(mod)
    mod.on_event("clipboard.receive", {"mime_type": "text/plain", "size_bytes": 5, "content": "secret"})
    assert len(lines) == 1
    ev = json.loads(lines[0])
    assert set(ev) == FIELDS
    assert ev["user"] == "alice" and ev["direction"] == "in"
    assert ev["size"] == 5 and ev["type"] == "text/plain" and ev["filename_hash"] is None
    assert "secret" not in lines[0]


def test_clipboard_out(monkeypatch):
    mod = _load()
    lines = _capture(mod)
    mod.on_event("clipboard.send", {"mime_type": "image/png", "size_bytes": 9})
    ev = json.loads(lines[0])
    assert set(ev) == FIELDS and ev["direction"] == "out" and ev["filename_hash"] is None


def test_file_upload_hashes_filename_no_plain_name():
    mod = _load()
    lines = _capture(mod)
    mod.on_event("file.upload.end", {"filename": "payroll.pdf", "size_bytes": 42})
    ev = json.loads(lines[0])
    assert set(ev) == FIELDS
    assert ev["direction"] == "in" and ev["size"] == 42 and ev["type"] == "application/pdf"
    assert ev["filename_hash"] == hashlib.sha256(b"payroll.pdf").hexdigest()
    assert "payroll" not in lines[0]


def test_other_events_ignored():
    mod = _load()
    lines = _capture(mod)
    mod.on_event("session.connect", {"transport": "websockets"})
    mod.on_event("file.upload.error", {"filename": "x", "error": "e"})
    assert lines == []


def test_patch_hooks_audit_emit_and_is_in_series():
    text = PATCH.read_text()
    assert "+++ b/selkies/audit.py" in text and "styx_audit.on_event(event, fields)" in text
    assert PATCH.name in (PATCH.parent / "series").read_text().split()
