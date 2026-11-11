"""Launch SLI metrics (exposed on the internal /metrics port via the default registry).

Labels are fixed enums only: no user/instance/image labels (cardinality).
"""
import time

from prometheus_client import Counter, Histogram

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
