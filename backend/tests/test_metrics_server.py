from unittest.mock import patch

from app.services import prom_metrics


def test_port_zero_does_not_start(monkeypatch):
    monkeypatch.setattr(prom_metrics, "_started", False)
    with patch("prometheus_client.start_http_server") as m:
        assert prom_metrics.start_metrics_server(0) is False
    m.assert_not_called()


def test_port_9000_starts_once(monkeypatch):
    monkeypatch.setattr(prom_metrics, "_started", False)
    with patch("prometheus_client.start_http_server") as m:
        assert prom_metrics.start_metrics_server(9000) is True
        prom_metrics.start_metrics_server(9000)
    m.assert_called_once_with(9000)
