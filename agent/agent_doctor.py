"""`styx-agent doctor`: environment diagnostics (split from styx_agent.py)."""
import socket
import subprocess
from pathlib import Path

import engine
import seat_gnome
from health import seat_advisories
from portal_api import check_pin
from agent_procs import _check


def doctor(cfg: dict, api, host_tuning_checks, config_path: Path,
           log_dir: Path) -> int:
    """api/host_tuning_checks are injected by styx_agent (patchable there)."""
    print("styx-agent doctor:")
    ok = True
    ok &= _check("config readable", True, str(config_path))
    install = Path(cfg["install_dir"])
    ok &= _check("venv present", (install / "venv/bin/python").exists())
    ok &= _check("selkies 2.x installed", (install / "venv/bin/selkies").exists())
    ok &= _check(f"mode: {cfg.get('mode', 'mirror')}", True)
    if cfg.get("mode") == "mirror":
        xa = engine._find_xauthority(cfg)
        ok &= _check("XAUTHORITY found", xa is not None, xa or "none")
    dri = engine.pick_dri_node()
    _check("GPU render node", bool(dri), dri or "CPU encode")
    mon = engine.resolve_monitor_source()
    ok &= _check("audio monitor source", bool(mon), mon or "no pulse/pipewire")
    svc = subprocess.run(["systemctl", "--user", "is-active", "styx-agent"],
                         capture_output=True, text=True)
    ok &= _check("service active", svc.stdout.strip() == "active",
                 svc.stdout.strip())
    port_busy = socket.socket().connect_ex(("127.0.0.1", cfg["port"])) == 0
    ok &= _check(f"gateway listening :{cfg['port']}", port_busy,
                 "" if port_busy else "nothing listening — see logs/gateway.log")
    if cfg.get("ca_pin"):
        ok &= _check("TLS pin matches",
                     check_pin(cfg.get("server_cert", ""), cfg["ca_pin"]))
    try:
        api(cfg, "/api/agent/heartbeat", {"status": "online"})
        ok &= _check("server reachable + token valid", True)
    except Exception as e:
        ok &= _check("server reachable + token valid", False, str(e))
    seat = cfg.get("mode") == "seat" and seat_advisories(seat_gnome.gnome_available())
    for label, good, detail in host_tuning_checks() + (seat or []):
        _check(label, good, detail)   # advisory: not folded into `ok`
    print("All checks passed." if ok else f"Some checks failed. Logs: {log_dir}")
    return 0 if ok else 1
