"""Set the OSD mClock profile by business hours (idempotent, run by CronJob)."""

import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

log = logging.getLogger("mclock_throttle")

CLIENT = "high_client_ops"
RECOVERY = "high_recovery_ops"
VALID = {CLIENT, RECOVERY}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class Window:
    days: frozenset
    start: time
    end: time
    tz: ZoneInfo


def parse_window(spec: str) -> Window:
    """Parse 'Mon-Fri 07:00-19:00 America/New_York'."""
    days_s, hours_s, tz_s = spec.split()
    days = set()
    for part in days_s.split(","):
        a, _, b = part.partition("-")
        i, j = DAYS.index(a), DAYS.index(b or a)
        days.update(range(i, j + 1))
    s, e = (time.fromisoformat(x) for x in hours_s.split("-"))
    return Window(frozenset(days), s, e, ZoneInfo(tz_s))


def profile_for(now: datetime, window: Window, override: str = "") -> str:
    override = (override or "").strip()
    if override:
        if override in VALID:
            return override
        log.warning("invalid force override %r ignored; using schedule", override)
    local = now.astimezone(window.tz)
    inside = local.weekday() in window.days and window.start <= local.time() < window.end
    return CLIENT if inside else RECOVERY


def run_ceph(argv: list[str]) -> str:
    return subprocess.run(
        argv, capture_output=True, text=True, check=True, timeout=60
    ).stdout


def _ceph_env(env) -> None:
    """Build CEPH_ARGS for client.throttle from the mounted secret + mon endpoints."""
    mons = env.get("ROOK_MON_ENDPOINTS")
    keyfile = env.get("THROTTLE_KEY_FILE")
    if not (mons and keyfile):
        return
    hosts = ",".join(m.split("=", 1)[-1] for m in mons.split(","))
    with open(keyfile) as f:
        key = f.read().strip()
    ring = "/tmp/throttle.keyring"
    fd = os.open(ring, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"[client.throttle]\n    key = {key}\n")
    os.environ["CEPH_ARGS"] = f"--id throttle --keyring {ring} --mon-host {hosts}"


def main(env=None, runner=run_ceph, now=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    env = os.environ if env is None else env
    try:
        window = parse_window(env["THROTTLE_WINDOW"])
        want = profile_for(now or datetime.now(ZoneInfo("UTC")), window, env.get("THROTTLE_FORCE", ""))
        _ceph_env(env)
        cur = runner(["ceph", "config", "get", "osd", "osd_mclock_profile"]).strip()
        if cur == want:
            log.info("profile already %s", want)
            return 0
        runner(["ceph", "config", "set", "osd", "osd_mclock_profile", want])
        log.info("profile %s -> %s", cur, want)
        return 0
    except Exception as exc:  # noqa: BLE001 - any failure must fail the job
        log.error("throttle failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
