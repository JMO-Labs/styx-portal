"""Fake Styx portal for the kind load-test smoke: no Docker, GPU or desktops.

Implements what e2e/stream-ab/fleet.py + soak_fleet.py use: login, instance create/start/get/delete
(status becomes "running" READY_AFTER seconds after create) and a page on every other path
(any Host) for `--probe http`. Stdlib only."""
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

READY_AFTER = float(os.environ.get("READY_AFTER", "2"))
INSTANCES: dict[str, dict] = {}
LOCK = threading.Lock()


def view(inst: dict, now: float | None = None) -> dict:
    now = time.monotonic() if now is None else now
    running = inst["started"] is not None and now - inst["started"] >= READY_AFTER
    return {"id": inst["id"], "name": inst["name"], "subdomain": inst["subdomain"],
            "status": "running" if running else "starting"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body=None, headers=None, ctype="application/json") -> None:
        data = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _iid(self) -> str | None:
        parts = self.path.split("?")[0].strip("/").split("/")
        return parts[2] if parts[:2] == ["api", "instances"] and len(parts) > 2 else None

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/auth/login":
            return self._send(200, {"ok": True}, {"Set-Cookie": "csrf_token=fake; Path=/"})
        if path == "/api/instances":
            body = self._json()
            inst = {"id": uuid.uuid4().hex[:8], "name": body.get("name", ""),
                    "subdomain": body.get("subdomain", ""), "started": time.monotonic()}
            with LOCK:
                INSTANCES[inst["id"]] = inst
            return self._send(201, view(inst))
        iid = self._iid()
        if iid and path.endswith("/start") and iid in INSTANCES:
            return self._send(200, view(INSTANCES[iid]))
        self._send(404, {"detail": "not found"})

    def do_GET(self):  # noqa: N802
        iid = self._iid()
        if iid:
            inst = INSTANCES.get(iid)
            return self._send(200, view(inst)) if inst else self._send(404, {"detail": "not found"})
        host = (self.headers.get("Host") or "").split(":")[0].split(".")[0]
        self._send(200, f"<html><body>session {host}</body></html>".encode(), ctype="text/html")

    def do_DELETE(self):  # noqa: N802
        iid = self._iid()
        with LOCK:
            found = INSTANCES.pop(iid, None) if iid else None
        self._send(204 if found else 404)

    def log_message(self, *_):
        pass


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
