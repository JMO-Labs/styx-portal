"""ECS JSON lines for the SIEM (styx-portal#11, ADR-0044).

One JSON object per line on the ``styx.audit`` logger (stdout, no prefix);
Fluent Bit tails the container log and routes ``event.dataset`` to Elastic.
"""
import hashlib
import json
import logging
import sys
import uuid
from datetime import datetime, timezone

ECS_VERSION = "8.17.0"

log = logging.getLogger("styx.audit")
log.propagate = False  # keep the line raw; root handlers would add prefixes
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_h)

_CATEGORY = {"auth": "authentication", "user": "iam", "group": "iam", "invite": "iam",
             "settings": "configuration", "provider": "configuration",
             "service": "configuration"}
# Ordered: first verb prefix that matches wins; the fallback depends on category.
_TYPES = (("logout", "end"), ("login", "start"),
          ("create", "creation"), ("signup", "creation"), ("accept_invite", "creation"),
          ("delete", "deletion"), ("remove", "deletion"), ("purge", "deletion"))


def _classify(action: str) -> tuple[str, str, str]:
    prefix, _, verb = action.partition(".")
    category = _CATEGORY.get(prefix, "process")
    etype = next((t for v, t in _TYPES if verb.startswith(v)),
                 "info" if category == "authentication" else "change")
    failed = (verb.endswith("_locked") or verb == "refresh_reuse" or "fail" in verb
              or verb.endswith("denied"))
    return category, etype, "failure" if failed else "success"


def _ts(ts: datetime | None) -> str:
    ts = (ts or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def _prune(d: dict) -> dict:
    """Drop None values and empty sub-objects, recursively (ECS: omit unknowns)."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict) and k != "detail":
            v = _prune(v)
        if v is not None and v != {}:
            out[k] = v
    return out


def _base(dataset: str, action: str, ts: datetime | None = None) -> dict:
    return {"@timestamp": _ts(ts), "ecs": {"version": ECS_VERSION},
            "event": {"id": str(uuid.uuid4()), "kind": "event", "module": "styx",
                      "dataset": dataset, "provider": "styx-portal", "action": action}}


def audit_event(action: str, *, ts: datetime | None = None, user_id: str | None = None,
                user_name: str | None = None, actor_ip: str | None = None,
                resource: str | None = None, detail: dict | None = None) -> dict:
    """``detail`` must already be redacted by the caller."""
    ev = _base("styx.audit", action, ts)
    category, etype, outcome = _classify(action)
    ev["event"].update(category=[category], type=[etype], outcome=outcome)
    ev.update(user={"id": user_id, "name": user_name}, source={"ip": actor_ip},
              styx={"audit": {"resource": resource, "detail": detail}})
    return _prune(ev)


_SESSION_TYPES = {"session.launch": "start", "session.connect": "start",
                  "session.stop": "end", "session.disconnect": "end",
                  "session.lock": "change", "session.unlock": "change"}


def session_event(action: str, *, session_id: str, kind: str, user_id: str | None = None,
                  user_name: str | None = None, reason: str | None = None,
                  viewer_id: str | None = None, image_digest: str | None = None,
                  node: str | None = None, groups: list[str] | None = None,
                  ts: datetime | None = None) -> dict:
    """Session lifecycle -> ``styx.audit`` (instance or workstation stream)."""
    if action not in _SESSION_TYPES:
        raise ValueError(f"session action must be one of {sorted(_SESSION_TYPES)}, got {action!r}")
    ev = _base("styx.audit", action, ts)
    ev["event"].update(category=["session"], type=[_SESSION_TYPES[action]], outcome="success")
    ev.update(user={"id": user_id, "name": user_name}, host={"name": node},
              container={"image": {"hash": {"all": [image_digest] if image_digest else None}}},
              styx={"session": {"id": session_id, "kind": kind, "reason": reason,
                                "viewer_id": viewer_id, "groups": groups or None}})
    return _prune(ev)


def egress_event(*, domain: str, action: str, method: str | None = None,
                 user_name: str | None = None, rule_category: str | None = None,
                 ts: datetime | None = None) -> dict:
    """Phase 3 hook: Squid hostname decision -> ``logs-styx.egress-*``."""
    if action not in ("allowed", "blocked"):
        raise ValueError(f"egress action must be allowed|blocked, got {action!r}")
    ev = _base("styx.egress", action, ts)
    ev["event"].update(category=["network"], type=["allowed" if action == "allowed" else "denied"],
                       outcome="success" if action == "allowed" else "failure")
    ev.update(url={"domain": domain}, destination={"domain": domain},
              http={"request": {"method": method}}, rule={"category": rule_category},
              user={"name": user_name})
    return _prune(ev)


def dlp_event(*, direction: str, channel: str, filename: str | None = None,
              size: int | None = None, mime_type: str | None = None,
              user_name: str | None = None, ts: datetime | None = None) -> dict:
    """Phase 4 hook: clipboard/file transfer metadata -> ``logs-styx.dlp-*``.

    Metadata only (D38): never content, never ``file.hash.*`` (ECS means a content
    hash there); the filename itself is only kept as a sha256.
    """
    if direction not in ("in", "out") or channel not in ("clipboard", "file"):
        raise ValueError("dlp direction must be in|out and channel clipboard|file")
    ev = _base("styx.dlp", f"{channel}.{direction}", ts)
    ev["event"].update(category=["file"], type=["access"], outcome="success")
    fn_hash = hashlib.sha256(filename.encode()).hexdigest() if filename else None
    ev.update(file={"size": size, "mime_type": mime_type}, user={"name": user_name},
              styx={"dlp": {"direction": direction, "channel": channel,
                            "filename_sha256": fn_hash}})
    return _prune(ev)


def emit(event: dict) -> None:
    log.info(json.dumps(event, default=str, separators=(",", ":")))
