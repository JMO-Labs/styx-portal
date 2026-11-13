"""Concurrent fleet launcher: create N instances, time create -> running."""
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass


class HttpClient:
    """Small injectable client: base URL + auth headers/cookies."""

    def __init__(self, base_url, headers=None, cookies=None, timeout=30):
        self.base = base_url.rstrip("/")
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.timeout = timeout

    def request(self, method, path, json=None):
        import requests

        r = requests.request(method, self.base + path, json=json, headers=self.headers,
                             cookies=self.cookies, timeout=self.timeout)
        r.raise_for_status()
        return r.json() if r.content else None


@dataclass
class Session:
    name: str
    id: str | None = None
    launch_s: float | None = None
    error: str | None = None


def _launch_one(client, name, template, timeout_s, poll_s):
    s = Session(name=name)
    t0 = time.monotonic()
    try:
        inst = client.request("POST", "/api/instances",
                              {"template_id": template, "name": name, "subdomain": name})
        s.id = inst["id"]
        # create already schedules a background launch for starting/pulling
        if inst.get("status") == "stopped":
            client.request("POST", f"/api/instances/{s.id}/start")
        while True:
            status = client.request("GET", f"/api/instances/{s.id}").get("status")
            if status == "running":
                s.launch_s = time.monotonic() - t0
                return s
            if status == "error":
                s.error = "instance status error"
                return s
            if time.monotonic() - t0 >= timeout_s:
                s.error = f"timeout after {timeout_s}s"
                return s
            time.sleep(poll_s)
    except Exception as e:  # noqa: BLE001
        s.error = str(e)
        return s


def launch(client, n, template, timeout_s, poll_s=1.0, prefix="fleet"):
    """Launch n sessions concurrently; returns Sessions in creation order."""
    with ThreadPoolExecutor(max_workers=max(n, 1)) as ex:
        futs = [ex.submit(_launch_one, client, f"{prefix}-{i}", template, timeout_s, poll_s)
                for i in range(n)]
        return [f.result() for f in futs]


def teardown(client, sessions):
    """Delete every created instance; keep going on errors. Returns error strings."""
    errors = []
    for s in sessions:
        if not s.id:
            continue
        try:
            client.request("DELETE", f"/api/instances/{s.id}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{s.id}: {e}")
    return errors
