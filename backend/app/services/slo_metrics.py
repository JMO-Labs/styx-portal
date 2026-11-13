"""Launch SLI metrics (exposed on the internal /metrics port via the default registry).

Labels are fixed enums only: no user/instance/image labels (cardinality).
"""
import logging
import time
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

from prometheus_client import Counter, Gauge, Histogram

from app.config import Settings

logger = logging.getLogger("styx-portal")

BUCKETS = (1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30, 60, 120)
KINDS = {"create", "start", "resume"}
OUTCOMES = {"ok", "error", "timeout"}
REASONS = {"capacity", "image", "timeout", "other"}

LAUNCH_DURATION = Histogram(
    "styx_launch_duration_seconds",
    "Seconds from launch request acceptance until the instance is running",
    ["kind", "outcome"],
    buckets=BUCKETS,
)
LAUNCH_FAILURES = Counter(
    "styx_launch_failures_total",
    "Failed instance launches by reason",
    ["reason"],
)


def observe_launch(kind: str, outcome: str, seconds: float) -> None:
    LAUNCH_DURATION.labels(
        kind if kind in KINDS else "start",
        outcome if outcome in OUTCOMES else "error",
    ).observe(max(seconds, 0.0))


def observe_since(kind: str, outcome: str, requested_at: float | None) -> None:
    """Observe elapsed time since a time.monotonic() timestamp; no-op if unknown."""
    if requested_at is not None:
        observe_launch(kind, outcome, time.monotonic() - requested_at)


def record_launch_failure(reason: str) -> None:
    LAUNCH_FAILURES.labels(reason if reason in REASONS else "other").inc()


_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def in_business_hours(cfg: Settings, now: datetime) -> bool:
    local = now.astimezone(ZoneInfo(cfg.SLO_TIMEZONE))
    days = {d.strip()[:3].lower() for d in cfg.SLO_BUSINESS_DAYS.split(",") if d.strip()}
    if _DAYS[local.weekday()] not in days:
        return False
    start_s, end_s = cfg.SLO_BUSINESS_HOURS.split("-")
    return dtime.fromisoformat(start_s.strip()) <= local.time().replace(tzinfo=None) \
        < dtime.fromisoformat(end_s.strip())


def in_maintenance(cfg: Settings, now: datetime) -> bool:
    if not (cfg.SLO_MAINTENANCE_START and cfg.SLO_MAINTENANCE_END):
        return False
    return _parse_dt(cfg.SLO_MAINTENANCE_START) <= now < _parse_dt(cfg.SLO_MAINTENANCE_END)


def _safe(fn) -> float:
    """Evaluate at scrape time; bad config must not break /metrics (reports 0)."""
    try:
        return 1.0 if fn(Settings(), _utcnow()) else 0.0
    except Exception:
        logger.exception("SLO scope gauge misconfigured")
        return 0.0


BUSINESS_HOURS = Gauge(
    "styx_slo_business_hours", "1 inside configured SLO business hours, else 0")
BUSINESS_HOURS.set_function(lambda: _safe(in_business_hours))
MAINTENANCE_ACTIVE = Gauge(
    "styx_maintenance_active", "1 while a configured maintenance window is active")
MAINTENANCE_ACTIVE.set_function(lambda: _safe(in_maintenance))
