"""Wiring for the gateway's DLP metadata reporter (kept out of gateway.py)."""
import json
import os
import sys
from pathlib import Path

from gateway_dlp import DlpReporter, portal_poster

DEFAULT_CONFIG = Path.home() / ".config/styx-agent/config.json"


def build_reporter(config_path: str | None = None) -> DlpReporter | None:
    """DlpReporter posting to the portal with the agent's enrollment config
    (STYX_AGENT_CONFIG overrides the path); None if the config is unusable."""
    path = config_path or os.environ.get("STYX_AGENT_CONFIG") or DEFAULT_CONFIG
    try:
        cfg = json.loads(Path(path).read_text())
        if not (cfg.get("server") and cfg.get("agent_token")):
            return None
    except (OSError, ValueError):
        return None
    return DlpReporter(portal_poster(cfg), log=lambda m: print(m, file=sys.stderr))
