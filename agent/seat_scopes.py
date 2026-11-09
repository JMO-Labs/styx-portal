"""Give seat apps their own systemd scopes so systemd-oomd kills the hungry app,
not the whole seat.

gnome-shell on the seat runs on a private dbus-run-session bus, so it never
creates the usual app-gnome-*.scope: every app lands in styx-agent.service and
oomd, which kills whole cgroups, takes the desktop down with it (2026-11-06,
2026-11-08). The agent moves each app gnome-shell launched (plus its whole
process tree) into app-styx-<comm>-<pid>.scope on the real user manager.
"""
import os
import re
import subprocess
from pathlib import Path

UNIT = "styx-agent.service"
SHELL = "gnome-shell"
INFRA = {"ibus-daemon", "gjs", "Xwayland"}   # shell helpers stay with the seat


def _proc_table() -> tuple[dict[int, list[int]], dict[int, str]]:
    """(ppid -> child pids, pid -> comm) for every visible process."""
    kids: dict[int, list[int]] = {}
    comm: dict[int, str] = {}
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            stat = (p / "stat").read_text()
        except OSError:
            continue
        pid = int(p.name)
        comm[pid] = stat[stat.index("(") + 1:stat.rindex(")")]
        kids.setdefault(int(stat[stat.rindex(")") + 2:].split()[1]), []).append(pid)
    return kids, comm


def _in_agent(pid: int) -> bool:
    try:
        return f"/{UNIT}" in Path(f"/proc/{pid}/cgroup").read_text()
    except OSError:
        return False


def plan(kids: dict[int, list[int]], comm: dict[int, str],
         in_agent=_in_agent) -> list[tuple[str, list[int]]]:
    """[(scope name, pids)] for each app child of the seat's gnome-shell."""
    out = []
    for shell in (p for p, c in comm.items() if c == SHELL and in_agent(p)):
        for app in kids.get(shell, []):
            if comm.get(app) in INFRA or not in_agent(app):
                continue
            tree, todo = [], [app]
            while todo:
                pid = todo.pop()
                tree.append(pid)
                todo += kids.get(pid, [])
            name = re.sub(r"[^A-Za-z0-9_.-]", "_", comm.get(app, "app"))
            out.append((f"app-styx-{name}-{app}.scope", sorted(tree)))
    return out


def sweep() -> None:
    # Pin the real user bus: a process started from a seat terminal inherits the
    # seat's private bus, where systemd1 is absent ("Access denied").
    env = {**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + os.environ.get(
        "XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}") + "/bus"}
    kids, comm = _proc_table()
    for name, pids in plan(kids, comm):
        subprocess.run(
            ["busctl", "--user", "call", "org.freedesktop.systemd1",
             "/org/freedesktop/systemd1", "org.freedesktop.systemd1.Manager",
             "StartTransientUnit", "ssa(sv)a(sa(sv))", name, "fail", "2",
             "PIDs", "au", str(len(pids)), *map(str, pids),
             "CollectMode", "s", "inactive-or-failed", "0"],
            env=env, capture_output=True, timeout=10)


def protect_agent() -> None:
    """Make oomd prefer any other cgroup over the agent (persists as a drop-in;
    honored for user units under memory pressure)."""
    subprocess.run(["systemctl", "--user", "set-property", UNIT,
                    "ManagedOOMPreference=avoid"], capture_output=True, timeout=10)
