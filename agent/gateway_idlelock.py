"""Idle lock mode (ADR-0039): lock instead of close; a signed token unlocks.

Token = <instance_id>.<expiry_unix>.<hex HMAC-SHA256(key, "<instance_id>.<expiry_unix>")>,
valid for at most TOKEN_MAX_S. Off when lock_idle_s is 0.
"""
import hashlib
import asyncio
import hmac
import html as _html
import time

from aiohttp import web

LOCK_CODE = 4003
TOKEN_MAX_S = 60


def verify_token(token: str, key: str, instance_id: str, now: float | None = None) -> bool:
    if not key or not token:
        return False
    iid, _, rest = token.partition(".")
    exp_s, _, sig = rest.partition(".")
    if not exp_s.isdigit() or not sig or iid != instance_id:
        return False
    now = time.time() if now is None else now
    exp = int(exp_s)
    if not now < exp <= now + TOKEN_MAX_S:
        return False
    want = hmac.new(key.encode(), f"{iid}.{exp_s}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig.encode(), want.encode())


def lock_page(unlock_url: str) -> str:
    href = _html.escape(unlock_url, quote=True)
    return ("<!doctype html><meta charset='utf-8'><title>Locked</title>"
            "<style>body{margin:0;height:100vh;display:grid;place-items:center;"
            "background:#0b0d12;color:#e6e8ee;font:16px system-ui,sans-serif}"
            "div{text-align:center}a{display:inline-block;margin-top:1em;"
            "padding:.6em 1.4em;border-radius:8px;background:#6d5efc;color:#fff;"
            "text-decoration:none}</style>"
            f"<div><h1>Session locked</h1><p>Locked after inactivity.</p>"
            f"<a href=\"{href}\">Unlock</a></div>")


class IdleLock:
    def __init__(self, lock_idle_s=0, unlock_url="", unlock_key="",
                 instance_id="", active=lambda: 0, log=print):
        self.idle_s, self.url = lock_idle_s, unlock_url
        self.key, self.iid = unlock_key, instance_id
        self.active, self.log = active, log
        self.locked_at: float | None = None
        self.last_disconnect: float | None = None
        self.socks: set = set()
        self.on_lock: list = []   # async callbacks (e.g. WebRTC gateway drop)

    @property
    def locked(self) -> bool:
        return self.locked_at is not None

    def register(self, ws):
        self.socks.add(ws)

    def unregister(self, ws):
        self.socks.discard(ws)
        self.stamp_disconnect()

    def stamp_disconnect(self):
        self.last_disconnect = time.time()

    async def lock(self):
        if self.locked:
            return
        self.locked_at = time.time()
        self.log("locked: idle")
        for ws in list(self.socks):
            await ws.close(code=LOCK_CODE, message=b"locked")
        for cb in self.on_lock:
            await cb()

    def idle_for(self, opened: float, last_input: float) -> float:
        return time.time() - max(opened, last_input)

    async def watch(self, ws, opened: float, rec):
        """Lock (not close) once this tab sent no input for lock_idle_s."""
        if self.idle_s <= 0:
            return
        while not ws.closed:
            idle = self.idle_for(opened, rec.last_input)
            if idle >= self.idle_s:
                await self.lock()
                return
            await asyncio.sleep(min(1.0, self.idle_s - idle))

    @web.middleware
    async def middleware(self, request, handler):
        if not self.locked or request.path.startswith("/styx/"):
            return await handler(request)
        if (request.headers.get("Upgrade", "").lower() != "websocket"
                and request.method == "GET"
                and "text/html" in request.headers.get("Accept", "")):
            return web.Response(status=423, text=lock_page(self.url),
                                content_type="text/html")
        return web.Response(status=423, text="locked")

    async def handle_unlock(self, request):
        if not verify_token(request.query.get("token", ""), self.key, self.iid):
            return web.Response(status=403, text="forbidden")
        self.locked_at = None
        self.log("unlocked")
        raise web.HTTPFound("/")

    async def handle_state(self, _request):
        return web.json_response({
            "locked": self.locked, "locked_at": self.locked_at,
            "active_connections": self.active(),
            "last_disconnect_ts": self.last_disconnect})
