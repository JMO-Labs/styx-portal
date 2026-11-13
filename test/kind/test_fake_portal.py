import importlib.util
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location("fake_portal", Path(__file__).with_name("fake-portal.py"))
fp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fp)


def call(base, method, path, body=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        return r.status, raw


def test_lifecycle_and_probe_page(monkeypatch):
    monkeypatch.setattr(fp, "READY_AFTER", 0.3)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), fp.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        assert call(base, "POST", "/api/auth/login", {"username": "u", "password": "p"})[0] == 200
        _, raw = call(base, "POST", "/api/instances", {"template_id": "t", "name": "fleet-0", "subdomain": "fleet-0"})
        inst = json.loads(raw)
        assert inst["status"] == "starting"
        time.sleep(0.4)
        assert json.loads(call(base, "GET", f"/api/instances/{inst['id']}")[1])["status"] == "running"
        assert call(base, "GET", "/")[0] == 200
        assert call(base, "DELETE", f"/api/instances/{inst['id']}")[0] == 204
    finally:
        srv.shutdown()
