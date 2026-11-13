"""Gateway side of the Selkies lock-overlay hook (patches/selkies/04-*).

The patched selkies blanks its video stream on `STYX_LOCK,1` and resumes on
`STYX_LOCK,0`. The idle policy that decides when to lock is out of scope (ADR-0039).
"""

LOCK_CMD = "STYX_LOCK"


async def send_lock(ws, locked: bool) -> None:
    """Send lock (True) or unlock (False) over an open selkies websocket."""
    await ws.send_str(f"{LOCK_CMD},{1 if locked else 0}")
