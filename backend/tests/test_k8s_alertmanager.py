from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2] / "deploy" / "k8s"


def _load(path):
    return list(yaml.safe_load_all((ROOT / path).read_text()))


def _cfg():
    (cfg,) = [d for d in _load("alertmanager-config.yaml") if d["kind"] == "AlertmanagerConfig"]
    return cfg["spec"]


def test_portal_receiver_always_with_resolved_and_token_secret():
    spec = _cfg()
    (portal,) = [r for r in spec["receivers"] if r["name"] == "portal"]
    (wh,) = portal["webhookConfigs"]
    assert wh["url"] == "http://backend.styx.svc:8000/internal/alerts/alertmanager"
    assert wh["sendResolved"] is True
    assert wh["httpConfig"]["authorization"]["credentials"]["name"] == "alertmanager-webhook-token"
    kinds = {d["kind"] for d in _load("alertmanager-config.yaml")}
    assert "ExternalSecret" in kinds


def test_root_and_watchdog_route_to_portal():
    route = _cfg()["route"]
    assert route["receiver"] == "portal"
    wd = [r for r in route["routes"] if r.get("receiver") == "portal" and r.get("matchers")]
    assert any(m["value"] == "Watchdog" for r in wd for m in r["matchers"])
    assert route["routes"][-1]["receiver"] == "portal"


def test_kustomization_lists_config_and_not_optional_components():
    k = yaml.safe_load((ROOT / "kustomization.yaml").read_text())
    assert "alertmanager-config.yaml" in k["resources"]
    assert not k.get("components")


def _patched(component):
    c = yaml.safe_load((ROOT / "components" / component / "kustomization.yaml").read_text())
    assert c["kind"] == "Component"
    return c


def test_matrix_component_stub():
    c = _patched("matrix")
    text = (ROOT / "components" / "matrix" / "kustomization.yaml").read_text()
    for needle in ("matrix-alertmanager-receiver", "continue: true", "America/New_York",
                   "business-hours", "activeTimeIntervals"):
        assert needle in text
    assert c["patches"]


def test_smtp_component_stub():
    c = _patched("smtp")
    text = (ROOT / "components" / "smtp" / "kustomization.yaml").read_text()
    assert "emailConfigs" in text
    assert c["patches"]


def test_networkpolicy_allows_monitoring_to_backend():
    pols = {d["metadata"]["name"]: d for d in _load("networkpolicy.yaml")}
    ing = pols["backend-alerts-ingress"]["spec"]
    assert ing["podSelector"]["matchLabels"] == {"app": "styx-backend"}
    (rule,) = ing["ingress"]
    (frm,) = rule["from"]
    assert frm["namespaceSelector"]["matchLabels"] == {"kubernetes.io/metadata.name": "monitoring"}
