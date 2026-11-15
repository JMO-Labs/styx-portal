"""Gateway CLI/env configuration."""
import os


def parse_env(argv):
    """-> (listen_port, upstream_port, user, password, create_app kwargs)."""
    kw = dict(
        files_dir=os.path.expanduser(os.environ.get("STYX_FILES_DIR", "~/Downloads")),
        state_file=os.environ.get("STYX_GW_STATE", ""),
        idle_timeout_s=int(os.environ.get("STYX_GW_IDLE_TIMEOUT_S", "0") or "0"),
        idle_lead_s=int(os.environ.get("STYX_GW_IDLE_WARN_S", "60") or "60"),
        idle_enabled=os.environ.get("STYX_GW_IDLE_ENABLED", "") == "1",
        seat_dir=os.environ.get("STYX_GW_SEAT_DIR", ""),
        icon_dir=os.environ.get("STYX_GW_ICON_DIR", ""),
        transport=os.environ.get("STYX_GW_TRANSPORT", ""),
        max_session_s=int(os.environ.get("STYX_GW_MAX_SESSION_S", "0") or "0"),
        webrtc_off=os.environ.get("STYX_GW_WEBRTC_OFF", "") == "1",
    )
    return (int(argv[1]), int(argv[2]), os.environ["STYX_GW_USER"],
            os.environ["STYX_GW_PASSWORD"], kw)
