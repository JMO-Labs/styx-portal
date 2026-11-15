"""Dev/harness override file for selkies (flags + cc_trace)."""
import json
from pathlib import Path

STREAM_OVERRIDE = Path.home() / ".local/share/styx-agent/stream-override.json"


def _read_override(path: Path) -> dict:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        d = None
    return d if isinstance(d, dict) else {}


def apply_stream_override(argv: list, path: Path = STREAM_OVERRIDE) -> list:
    """argv plus the selkies flags in `path` ({"args": [...]}), which win as
    argparse keeps the last value. The stream A/B harness swaps encoder and
    bitrate this way and restarts only selkies, so the seat survives.
    ponytail: dev/harness hook; production settings still come from the portal."""
    extra = _read_override(path).get("args", [])
    ok = isinstance(extra, list) and all(isinstance(a, str) for a in extra)
    return argv + extra if ok else argv


def cc_trace_enabled(path: Path = STREAM_OVERRIDE) -> bool:
    """`cc_trace` in the override file: log STYX-CC lines (default off)."""
    return _read_override(path).get("cc_trace") is True
