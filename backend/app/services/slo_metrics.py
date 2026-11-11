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


RTT_KEYS = (".01", ".02", ".04", ".06", ".08", ".1", ".15", ".25", ".5", "1", "+Inf")
RTT_BUCKETS = (0.01, 0.02, 0.04, 0.06, 0.08, 0.1, 0.15, 0.25, 0.5, 1.0)
TRANSPORTS = ("webrtc", "websocket")

STREAM_RTT = Histogram(
    "styx_stream_rtt_seconds",
    "Client-reported stream network round-trip time (proxy for latency, not input-to-photon)",
    ["transport"],
    buckets=RTT_BUCKETS,
)
for _t in TRANSPORTS:  # fixed series set, created up front
    STREAM_RTT.labels(_t)


def observe_rtt_buckets(transport: str, counts: dict[str, int], total_sum: float) -> None:
    """Add pre-bucketed (non-cumulative) client counts; keys must be in RTT_KEYS (validated)."""
    child = STREAM_RTT.labels(transport)
    for key, n in counts.items():
        if n:
            child._buckets[RTT_KEYS.index(key)].inc(n)  # prometheus_client has no bulk observe
    child._sum.inc(total_sum)
