"""Viewer connect/disconnect spool shared by the gateway and the agent.

The gateway process appends JSONL records; the agent's heartbeat reads them,
and removes only what it sent once the server accepted it. Capped at MAX
records, oldest dropped first. Writers and the acker serialise on flock."""
import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone

MAX = 100
NAME = "session_events.jsonl"


@contextmanager
def _lock(path):
    with open(str(path) + ".lock", "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        yield


def _lines(path) -> list[str]:
    try:
        with open(path) as f:
            return [ln for ln in f.read().splitlines() if ln.strip()]
    except OSError:
        return []


def _write(path, lines) -> None:
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        f.write("".join(ln + "\n" for ln in lines))
    os.replace(tmp, path)


def record(path, action: str, viewer_id: str) -> None:
    """Append one event; never raises (telemetry must not break streaming)."""
    try:
        ev = {"action": action, "viewer_id": viewer_id,
              "ts": datetime.now(timezone.utc).isoformat()}
        with _lock(path):
            _write(path, (_lines(path) + [json.dumps(ev)])[-MAX:])
    except OSError:
        pass


def pending(path) -> tuple[list[dict], int]:
    """(events, n): up to MAX queued events and how many lines they cover."""
    lines = _lines(path)[:MAX]
    evs = []
    for ln in lines:
        try:
            evs.append(json.loads(ln))
        except ValueError:
            pass
    return evs, len(lines)


def ack(path, n: int) -> None:
    """Drop the first n queued lines (the ones the heartbeat delivered)."""
    if n <= 0:
        return
    try:
        with _lock(path):
            _write(path, _lines(path)[n:])
    except OSError:
        pass
