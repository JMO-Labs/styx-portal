from prometheus_client import REGISTRY

from app.services import slo_metrics


def _val(name, labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_launch_histogram_buckets_include_5_and_10():
    slo_metrics.observe_launch("create", "ok", 0.5)
    les = {s.labels["le"] for m in REGISTRY.collect() if m.name == "styx_launch_duration_seconds"
           for s in m.samples if s.name.endswith("_bucket")}
    assert les == {"1.0", "2.0", "3.0", "4.0", "5.0", "6.0", "8.0", "10.0", "15.0",
                   "20.0", "30.0", "60.0", "120.0", "+Inf"}


def test_launch_histogram_labels_are_kind_and_outcome_only():
    slo_metrics.observe_launch("create", "ok", 3.0)
    keys = {frozenset(set(s.labels) - {"le"}) for m in REGISTRY.collect()
            if m.name == "styx_launch_duration_seconds" for s in m.samples}
    assert keys <= {frozenset({"kind", "outcome"})}
    assert _val("styx_launch_duration_seconds_count", {"kind": "create", "outcome": "ok"}) >= 1


def test_launch_failure_reason_unknown_maps_to_other():
    before = _val("styx_launch_failures_total", {"reason": "other"})
    slo_metrics.record_launch_failure("weird")
    assert _val("styx_launch_failures_total", {"reason": "other"}) == before + 1
    before = _val("styx_launch_failures_total", {"reason": "capacity"})
    slo_metrics.record_launch_failure("capacity")
    assert _val("styx_launch_failures_total", {"reason": "capacity"}) == before + 1


# --- scope gauges -----------------------------------------------------------
from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402


def _freeze(monkeypatch, iso):
    monkeypatch.setattr(slo_metrics, "_utcnow",
                        lambda: datetime.fromisoformat(iso).replace(tzinfo=timezone.utc))


def _gauge(name):
    return REGISTRY.get_sample_value(name)


@pytest.mark.parametrize("iso,expected", [
    ("2026-03-09T11:30", 1.0),   # Mon 07:30 EDT
    ("2026-03-07T15:00", 0.0),   # Saturday
    ("2026-11-02T11:30", 0.0),   # Mon 06:30 EST (after DST end)
    ("2026-11-02T12:30", 1.0),   # Mon 07:30 EST
])
def test_business_hours_gauge_dst(monkeypatch, iso, expected):
    _freeze(monkeypatch, iso)
    assert _gauge("styx_slo_business_hours") == expected


def test_business_hours_respects_settings(monkeypatch):
    monkeypatch.setenv("SLO_TIMEZONE", "UTC")
    monkeypatch.setenv("SLO_BUSINESS_DAYS", "Sat,Sun")
    monkeypatch.setenv("SLO_BUSINESS_HOURS", "09:00-10:00")
    _freeze(monkeypatch, "2026-03-07T09:30")
    assert _gauge("styx_slo_business_hours") == 1.0
    _freeze(monkeypatch, "2026-03-09T09:30")
    assert _gauge("styx_slo_business_hours") == 0.0


def test_maintenance_gauge_inside_and_outside_window(monkeypatch):
    monkeypatch.setenv("SLO_MAINTENANCE_START", "2026-05-01T02:00:00+00:00")
    monkeypatch.setenv("SLO_MAINTENANCE_END", "2026-05-01T04:00:00+00:00")
    _freeze(monkeypatch, "2026-05-01T03:00")
    assert _gauge("styx_maintenance_active") == 1.0
    _freeze(monkeypatch, "2026-05-01T04:00")
    assert _gauge("styx_maintenance_active") == 0.0
    _freeze(monkeypatch, "2026-05-01T01:59")
    assert _gauge("styx_maintenance_active") == 0.0


def test_maintenance_gauge_unset_is_zero(monkeypatch):
    monkeypatch.delenv("SLO_MAINTENANCE_START", raising=False)
    monkeypatch.delenv("SLO_MAINTENANCE_END", raising=False)
    _freeze(monkeypatch, "2026-05-01T03:00")
    assert _gauge("styx_maintenance_active") == 0.0
