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
