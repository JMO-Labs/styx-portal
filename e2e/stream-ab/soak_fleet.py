"""Multi-session soak: fleet.launch -> session_probe.probe (parallel) -> gate.evaluate -> report.

    python3 soak.py --sessions 50 --minutes 10 [--probe stream|http] [--portal URL] [--template T]

Report: results/gate-<stamp>.{json,md}. Exit 0 on pass, 1 on fail. Sessions are always torn down.
Credentials: STYX_USER/STYX_PASS env, else ab.creds(); never printed."""
import argparse
import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import fleet
import gate
import session_probe

HERE = Path(__file__).resolve().parent
LAUNCH_TIMEOUT_S = 300


def add_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--sessions", type=int, help="multi-session mode: number of sessions")
    ap.add_argument("--probe", choices=("stream", "http"), default="stream")
    ap.add_argument("--portal", default=os.environ.get("STYX_PORTAL", "http://localhost:8000"))
    ap.add_argument("--template", default="selkies-desktop")


def parse(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=90)
    add_args(ap)
    return ap.parse_args(argv)


def env_creds() -> tuple[str, str]:
    user, pw = os.environ.get("STYX_USER"), os.environ.get("STYX_PASS")
    if user and pw:
        return user, pw
    import ab
    return ab.creds()


def portal_client(portal: str, user: str, pw: str) -> fleet.HttpClient:
    """Log in (cookie + double-submit CSRF) and return an HttpClient."""
    import requests
    r = requests.post(portal.rstrip("/") + "/api/auth/login", json={"username": user, "password": pw},
                      timeout=30)
    r.raise_for_status()
    cookies = r.cookies.get_dict()
    return fleet.HttpClient(portal, headers={"x-csrf-token": cookies.get("csrf_token", "")}, cookies=cookies)


def session_url(portal: str, name: str) -> str:
    u = urlsplit(portal)
    return f"{u.scheme}://{name}.{u.netloc}/"


def run(a, *, client, fleet_mod=fleet, probe_fn=session_probe.probe, results: Path = HERE / "results") -> int:
    sessions = []
    old = signal.signal(signal.SIGTERM, _term) if _main_thread() else None
    try:
        launched = fleet_mod.launch(client, a.sessions, a.template, LAUNCH_TIMEOUT_S, sessions=sessions)
        sessions[:] = launched
        sessions.sort(key=lambda s: int(s.name.rsplit('-', 1)[1]))
        up = [s for s in sessions if s.id and not s.error]
        ex = ThreadPoolExecutor(max_workers=max(len(up), 1))
        try:
            futs = {s.name: ex.submit(probe_fn, session_url(a.portal, s.name), a.minutes, a.probe)
                    for s in up}
            probed = {n: f.result() for n, f in futs.items()}
        finally:  # on interrupt don't wait for probes: teardown starts right away
            ex.shutdown(wait=False, cancel_futures=True)
        rows = [{"session": s.name, "launch_s": s.launch_s if not s.error else None,
                 "rtt_ms": probed.get(s.name, {}).get("rtt_ms", []),
                 "drops": probed.get(s.name, {}).get("drops", 0)} for s in sessions]
        result = gate.evaluate(rows)
        results.mkdir(parents=True, exist_ok=True)
        gate.write_report(result, results / f"gate-{time.strftime('%Y%m%d-%H%M%S')}")
        print(f"gate: {result['verdict']} ({result['n_sessions']} sessions)", flush=True)
        return 0 if result["verdict"] == "pass" else 1
    finally:
        for e in fleet_mod.teardown(client, sessions):
            print(f"teardown error: {e}", flush=True)
        if old is not None:
            signal.signal(signal.SIGTERM, old)


def _term(*_):
    raise KeyboardInterrupt


def _main_thread() -> bool:
    import threading
    return threading.current_thread() is threading.main_thread()
