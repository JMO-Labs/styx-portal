"""Gateway DLP filter for the selkies websocket relay (pure, no I/O).

Selkies enforces its own clipboard/file settings client-side, so a modified
client could ignore them. The gateway drops what the policy forbids instead.

Tokens (selkies 2.2.0 websockets_mode.py / input_handler.py; legacy file tokens
from the 2.0/2.1 protocol, which 2.2 replaced with HTTP POST /api/upload):
  in  clipboard write : cw cws cwd cwe (text), cb cbs cbd cbe (binary)
  in  clipboard read  : cr, REQUEST_CLIPBOARD  (gated by clipboard_out)
  out clipboard       : clipboard clipboard_binary clipboard_start
                        clipboard_data clipboard_finish clipboard_reply
                        clipboard_secret
  in  file upload     : FILE_UPLOAD_START/END text, binary frame 0x01 (chunk)
  out file download   : FILE_DOWNLOAD_* text
  0x05 binary         : gzip-wrapped control text, inflated and re-checked
Server->client binary 0x01 is Opus audio, so binary file chunks are "in" only.
"""
import asyncio
import zlib

# D38: clipboard both ways, upload in allowed, download out off.
DEFAULTS = {"clipboard_in": True, "clipboard_out": True, "upload": True, "download": False}

CLIP_IN = frozenset(("cw", "cws", "cwd", "cwe", "cb", "cbs", "cbd", "cbe"))
CLIP_READ = frozenset(("cr", "REQUEST_CLIPBOARD"))
CLIP_OUT = frozenset(("clipboard", "clipboard_binary", "clipboard_start", "clipboard_data",
                      "clipboard_finish", "clipboard_reply", "clipboard_secret"))
GZIP_OPCODE = 0x05
FILE_CHUNK_OPCODE = 0x01
MAX_INFLATED = 64 * 1024 * 1024


def _token(text: str) -> str:
    for i, c in enumerate(text):
        if c in ",:":
            return text[:i]
    return text


def _text_allowed(text: str, direction: str, p: dict) -> bool:
    tok = _token(text)
    if direction == "in":
        if tok in CLIP_IN:
            return p["clipboard_in"]
        if tok in CLIP_READ:
            return p["clipboard_out"]
        if tok.startswith("FILE_UPLOAD"):
            return p["upload"]
    elif direction == "out":
        if tok in CLIP_OUT:
            return p["clipboard_out"]
        if tok.startswith("FILE_DOWNLOAD"):
            return p["download"]
    return True


def allow_message(data, direction: str, policy: dict | None) -> bool:
    """True if the websocket message may be relayed. direction: "in" = browser
    to desktop, "out" = desktop to browser. data: str or bytes."""
    p = {**DEFAULTS, **(policy or {})}
    if isinstance(data, str):
        return _text_allowed(data, direction, p)
    if not data:
        return True
    if data[0] == GZIP_OPCODE:
        try:
            d = zlib.decompressobj(wbits=31)
            text = d.decompress(data[1:], MAX_INFLATED)
            if d.unconsumed_tail:
                return False
            return _text_allowed(text.decode("utf-8"), direction, p)
        except (zlib.error, UnicodeDecodeError):
            return False
    if direction == "in" and data[0] == FILE_CHUNK_OPCODE:
        return p["upload"]
    return True


def _inner_text(data):
    """Control text of a message (inflating 0x05 frames), or None for binary."""
    if isinstance(data, str):
        return data
    if data and data[0] == GZIP_OPCODE:
        try:
            d = zlib.decompressobj(wbits=31)
            return d.decompress(data[1:], MAX_INFLATED).decode("utf-8")
        except (zlib.error, UnicodeDecodeError):
            return None
    return None


def event_meta(data, direction: str) -> dict | None:
    """Metadata of a clipboard/file transfer message, or None if it is neither.
    Never includes content: size is the byte length of the whole message."""
    if not data:
        return None
    size = len(data.encode("utf-8")) if isinstance(data, str) else len(data)
    text = _inner_text(data)
    mime = name = None
    if text is None:
        if not (direction == "in" and data[0] == FILE_CHUNK_OPCODE):
            return None
        channel = "file"
    else:
        tok = _token(text)
        parts = text.replace(",", ":").split(":")
        if tok in CLIP_IN or tok in CLIP_READ or tok in CLIP_OUT:
            channel = "clipboard"
            if len(parts) > 1 and "/" in parts[1]:
                mime = parts[1]
        elif tok.startswith(("FILE_UPLOAD", "FILE_DOWNLOAD")):
            channel = "file"
            name = parts[1] if len(parts) > 1 and parts[1] else None
        else:
            return None
    return {"direction": direction, "channel": channel, "size": size,
            "mime_type": mime, "filename": name}


class DlpReporter:
    """Buffers transfer metadata and posts it in batches, at most every
    `interval` s. post(events) is a blocking callable run in a thread; errors
    are logged and the batch dropped, so the relay never waits or fails."""

    MAX_BUFFER = 1000

    def __init__(self, post, interval: float = 5.0, log=lambda m: None):
        self._post, self._interval, self._log = post, interval, log
        self._buf: list[dict] = []
        self._timer = None

    def record(self, data, direction: str, allowed: bool) -> None:
        meta = event_meta(data, direction)
        if meta is None:
            return
        if len(self._buf) < self.MAX_BUFFER:
            self._buf.append({**meta, "allowed": allowed})
        if self._timer is None:
            self._timer = asyncio.get_running_loop().call_later(
                self._interval, lambda: asyncio.ensure_future(self._flush()))

    async def _flush(self) -> None:
        batch, self._buf, self._timer = self._buf, [], None
        if not batch:
            return
        try:
            await asyncio.to_thread(self._post, batch)
        except Exception as e:  # noqa: BLE001 - dropped by design
            self._log(f"dlp-events post failed, dropped {len(batch)}: {e}")


def portal_poster(cfg: dict):
    """post(events) callable for DlpReporter: POST /api/agent/dlp-events."""
    from portal_api import api
    return lambda events: api(cfg, "/api/agent/dlp-events", {"events": events})
