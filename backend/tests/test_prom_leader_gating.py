"""Leader-owned DB gauges: only the leader replica exports them (#98, ADR-0056)."""
from prometheus_client import REGISTRY

from tests.test_prom_metrics import _seed, _sync_url


class _Elector:
    def __init__(self, leader):
        self.is_leader = leader


def _use_elector(monkeypatch, leader):
    from app.services import prom_collectors

    monkeypatch.setattr(prom_collectors, "get_elector", lambda: _Elector(leader))


def test_non_leader_exports_no_leader_owned_gauges(tmp_path, monkeypatch):
    from app.services import prom_collectors

    _seed(_sync_url(tmp_path, monkeypatch), instances=["running"], sessions=[False])
    _use_elector(monkeypatch, False)

    def boom(*a, **k):
        raise AssertionError("non-leader must not query the DB")

    monkeypatch.setattr(prom_collectors, "create_engine", boom)
    names = {s.name for m in REGISTRY.collect() for s in m.samples}
    for name in prom_collectors.LEADER_OWNED:
        assert name not in names


def test_leader_exports_db_gauges(tmp_path, monkeypatch):
    _seed(_sync_url(tmp_path, monkeypatch), instances=["running"], sessions=[False])
    _use_elector(monkeypatch, True)
    assert REGISTRY.get_sample_value("styx_instances", {"status": "running"}) == 1
    assert REGISTRY.get_sample_value("styx_stream_sessions_active") == 1


def test_per_replica_metrics_still_exported_on_non_leader(monkeypatch):
    _use_elector(monkeypatch, False)
    names = {m.name for m in REGISTRY.collect()}
    assert {"styx_http_request_duration_seconds", "styx_launch_duration_seconds",
            "styx_slo_business_hours"} <= names
