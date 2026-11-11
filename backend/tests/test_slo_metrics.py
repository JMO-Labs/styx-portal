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
