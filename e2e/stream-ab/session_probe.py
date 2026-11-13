"""Per-session probe: RTT samples and drops for one session over a duration.

mode="stream": repeated latency.mjs rounds (subprocess, JSON parsed); a failed round or a missed
sample is a drop. mode="http": timed GET once a second (no browser; used by the kind smoke).
Subprocess, HTTP, clock are injectable."""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUND_S = 60            # nominal duration of one latency.mjs round
ROUND_N = 20            # samples per input kind per round
HTTP_TIMEOUT = 5.0


def parse_round(out: str) -> tuple[list, int]:
    """latency.mjs JSON -> (rtt samples, drops). Null samples and sent-but-unreported count as drops."""
    d = json.loads(out)
    sent = d.get("sent") or {}
    rtt, drops = [], 0
    for kind, vals in (d.get("samples") or {}).items():
        good = [float(v) for v in vals if v is not None]
        rtt += good
        drops += (len(vals) - len(good)) + max(0, int(sent.get(kind, len(vals))) - len(vals))
    return rtt, drops


def _run(cmd: list) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=ROUND_S * 5, cwd=HERE)
    return p.returncode, p.stdout


def _get(url: str, timeout: float) -> int:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
        return r.status


def probe(session_url: str, minutes: float, mode: str = "stream", *, run=_run, get=_get,
          now=time.monotonic, sleep=time.sleep, round_s: float = ROUND_S) -> dict:
    if mode not in ("stream", "http"):
        raise ValueError(f"mode must be 'stream' or 'http', got {mode!r}")
    end = now() + minutes * 60
    rtt: list = []
    drops = 0
    if mode == "stream":
        cmd = ["node", str(HERE / "latency.mjs"), f"--url={session_url}", f"--n={ROUND_N}"]
        while now() < end:
            t0 = now()
            try:
                code, out = run(cmd)
                if code != 0:
                    raise RuntimeError(f"exit {code}")
                r, d = parse_round(out)
                rtt += r
                drops += d
            except Exception:  # noqa: BLE001 - any failed round is one drop
                drops += 1
            sleep(max(0.0, round_s - (now() - t0)))
        return {"rtt_ms": rtt, "drops": drops}
    while now() < end:
        t0 = now()
        try:
            if get(session_url, HTTP_TIMEOUT) >= 400:
                raise RuntimeError("http error")
            rtt.append((now() - t0) * 1000)
        except Exception:  # noqa: BLE001
            drops += 1
        sleep(max(0.0, 1.0 - (now() - t0)))
    return {"rtt_ms": rtt, "drops": drops}
