"""Scrape-time DB gauges (instances by status, active stream sessions).

Leader-owned (ADR-0056, #98): the values are cluster-wide DB state, so only the
leader replica exports them; non-leaders yield nothing and never query the DB.
Runs on the scrape thread, so it uses its own short-lived sync connection and never raises.
"""
import logging

from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import create_engine, text

from app.config import Settings
from app.services.leader import get_elector

logger = logging.getLogger(__name__)


def _sync_url() -> str:
    """Sync form of DATABASE_URL (drops the async driver, e.g. sqlite+aiosqlite)."""
    url = Settings().DATABASE_URL
    scheme, sep, rest = url.partition("://")
    return scheme.split("+", 1)[0] + sep + rest


LEADER_OWNED = ("styx_instances", "styx_stream_sessions_active")


def _families():
    return (
        GaugeMetricFamily("styx_instances", "Instances by status", labels=["status"]),
        GaugeMetricFamily("styx_stream_sessions_active", "Open stream sessions"),
    )


class DbGaugesCollector:
    def describe(self):
        """Static families so registration never queries the DB."""
        return list(_families())

    def collect(self):
        if not get_elector().is_leader:
            return
        try:
            engine = create_engine(_sync_url())
            try:
                with engine.connect() as conn:
                    by_status = conn.execute(
                        text("SELECT status, COUNT(*) FROM instances GROUP BY status")
                    ).all()
                    active = conn.execute(
                        text("SELECT COUNT(*) FROM stream_sessions WHERE ended_at IS NULL")
                    ).scalar_one()
            finally:
                engine.dispose()
        except Exception:  # noqa: BLE001 - a scrape must never fail on DB trouble
            logger.warning("DB gauges unavailable for this scrape", exc_info=True)
            return
        inst, sessions = _families()
        for status, n in by_status:
            inst.add_metric([str(status)], n)
        yield inst
        sessions.add_metric([], active)
        yield sessions
