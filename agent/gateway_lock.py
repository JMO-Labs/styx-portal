"""Gateway side of the Selkies lock-overlay hook (patches/selkies/04-*).

The patched selkies stops writing video frames on `STYX_LOCK,1,<token>` and resumes on
`STYX_LOCK,0,<token>`. The token is the shared secret `STYX_LOCK_TOKEN` that only the
gateway and the selkies process hold: viewer pages share the websocket but cannot lock
or unlock. The idle policy that decides when to lock is out of scope (ADR-0039).
"""
import os

LOCK_CMD = "STYX_LOCK"
TOKEN_ENV = "STYX_LOCK_TOKEN"


def lock_message(locked: bool, token: str) -> str:
    return f"{LOCK_CMD},{1 if locked else 0},{token}"


async def send_lock(ws, locked: bool, token: str | None = None) -> None:
    """Send lock (True) or unlock (False) over an open selkies websocket."""
    token = token if token is not None else os.environ.get(TOKEN_ENV, "")
    if not token:
        raise RuntimeError(f"{TOKEN_ENV} is not set")
    await ws.send_str(lock_message(locked, token))
