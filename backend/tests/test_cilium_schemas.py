"""Vendored Cilium CRD schemas for offline kubeconform validation."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

SCHEMAS = (
    Path(__file__).resolve().parents[2]
    / "deploy/k8s/components/cilium-baseline/schemas"
)


def test_kubeconform_schemas_vendored():
    for name in ("ciliumnetworkpolicy_v2.json", "ciliumclusterwidenetworkpolicy_v2.json"):
        data = json.loads((SCHEMAS / name).read_text())
        assert data["properties"]["spec"]
    assert "1.20.4" in (SCHEMAS / "README.md").read_text()


ROOT = Path(__file__).resolve().parents[2]


def test_base_builds_with_kustomize():
    """CI sets REQUIRE_KUSTOMIZE=1 so a missing binary fails instead of skipping."""
    if not shutil.which("kustomize"):
        if os.environ.get("REQUIRE_KUSTOMIZE") == "1":
            pytest.fail("kustomize required but not installed")
        pytest.skip("kustomize not installed")
    out = subprocess.run(
        ["kustomize", "build", str(ROOT / "deploy/k8s")],
        capture_output=True, text=True, check=True,
    )
    assert "kind: NetworkPolicy" in out.stdout


CNP = """\
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata: {name: t}
spec:
  endpointSelector: {}
  egress:
    - toEndpoints:
        - matchLabels: {app: x}
"""


def _check(manifest: str):
    if not (shutil.which("kubeconform") or os.environ.get("REQUIRE_KUSTOMIZE") != "1"):
        pytest.fail("kubeconform required but not installed")
    if not shutil.which("kubeconform"):
        pytest.skip("kubeconform not installed")
    return subprocess.run(
        [str(ROOT / "scripts/k8s_policy_check.sh"), "--stdin"],
        input=manifest, capture_output=True, text=True,
    )


def test_vendored_schema_is_used_by_check_script():
    ok = _check(CNP)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "Valid: 1, Invalid: 0, Errors: 0, Skipped: 0" in ok.stdout
    bad = _check(CNP.replace("endpointSelector: {}", "bogusField: 1"))
    assert bad.returncode != 0


def test_unknown_kind_fails():
    assert _check(CNP.replace("CiliumNetworkPolicy", "NoSuchKind")).returncode != 0


def test_servicemonitor_is_skipped_not_errored():
    sm = (
        "apiVersion: monitoring.coreos.com/v1\nkind: ServiceMonitor\n"
        "metadata: {name: t}\nspec: {}\n"
    )
    r = _check(sm)
    assert r.returncode == 0, r.stdout + r.stderr


def _closed_branches(node, path=""):
    """Yield paths of anyOf/oneOf/allOf branches closed with additionalProperties:false."""
    if isinstance(node, dict):
        for key in ("anyOf", "oneOf", "allOf"):
            for i, br in enumerate(node.get(key, [])):
                if isinstance(br, dict) and br.get("additionalProperties") is False:
                    yield f"{path}/{key}/{i}"
        for k, v in node.items():
            yield from _closed_branches(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _closed_branches(v, f"{path}/{i}")


@pytest.mark.parametrize(
    "name", ["ciliumnetworkpolicy_v2.json", "ciliumclusterwidenetworkpolicy_v2.json"]
)
def test_schema_branches_not_closed(name):
    """Required-only anyOf/oneOf branches must not forbid sibling spec fields."""
    data = json.loads((SCHEMAS / name).read_text())
    assert list(_closed_branches(data)) == []


# --- #57: Prometheus scrape, intra-namespace, Traefik/Styx path ---

NS_KEY = "k8s:io.kubernetes.pod.namespace"
PHASE1_NS = ["monitoring", "rook-ceph", "cnpg-system", "harbor", "openbao",
             "external-secrets", "velero", "kyverno", "traefik", "styx", "styx-backup"]


COMPONENT = ROOT / "deploy/k8s/components/cilium-baseline"


def _by_name():
    """Parse the component's CCNP files directly (no kustomize needed)."""
    out = {}
    for f in sorted(COMPONENT.glob("ccnp-*.yaml")):
        for d in yaml.safe_load_all(f.read_text()):
            if d and d["kind"] == "CiliumClusterwideNetworkPolicy":
                out[d["metadata"]["name"]] = d
    return out


def _ports(rule):
    return {int(p["port"]) for tp in rule.get("toPorts", []) for p in tp["ports"]}


def test_prometheus_scrape():
    p = _by_name()["allow-prometheus-egress"]
    assert p["spec"]["endpointSelector"]["matchLabels"] == {
        NS_KEY: "monitoring", "app.kubernetes.io/name": "prometheus"}
    ent = [r for r in p["spec"]["egress"] if "toEntities" in r]
    assert len(ent) == 1
    assert set(ent[0]["toEntities"]) == {"host", "remote-node", "kube-apiserver"}
    assert _ports(ent[0]) == {9962, 9963, 9965, 9100, 10250, 2381, 10257, 10259}
    assert {"toEndpoints": [{}]} in p["spec"]["egress"]


def test_prometheus_ingress_to_all_pods():
    p = _by_name()["allow-prometheus"]
    (r,) = p["spec"]["ingress"]
    assert r["fromEndpoints"] == [{"matchLabels": {
        NS_KEY: "monitoring", "app.kubernetes.io/name": "prometheus"}}]
    assert "toPorts" not in r


@pytest.mark.parametrize("ns", PHASE1_NS)
def test_intra_namespace_allows(ns):
    p = _by_name()[f"allow-intra-ns-{ns}"]
    peer = [{"matchLabels": {NS_KEY: ns}}]
    assert p["spec"]["endpointSelector"]["matchLabels"] == {NS_KEY: ns}
    assert p["spec"]["ingress"] == [{"fromEndpoints": peer}]
    assert p["spec"]["egress"] == [{"toEndpoints": peer}]


def test_intra_namespace_exactly_phase1():
    names = {n for n in _by_name() if n.startswith("allow-intra-ns-")}
    assert names == {f"allow-intra-ns-{n}" for n in PHASE1_NS}


def test_traefik_path():
    p = _by_name()["traefik"]
    assert p["spec"]["endpointSelector"]["matchLabels"] == {NS_KEY: "traefik"}
    (ing,) = p["spec"]["ingress"]
    assert ing["fromEntities"] == ["world"]
    assert _ports(ing) >= {80, 443}
    eg = {r["toEndpoints"][0]["matchLabels"][NS_KEY]: _ports(r)
          for r in p["spec"]["egress"] if "toEndpoints" in r}
    assert eg["styx"] == {8000, 3000}
    assert eg["styx-instances"] == {3000, 3001}


def test_styx_path():
    p = _by_name()["styx"]
    assert p["spec"]["endpointSelector"]["matchLabels"] == {NS_KEY: "styx"}
    assert any(r["fromEndpoints"][0]["matchLabels"][NS_KEY] == "traefik"
               for r in p["spec"]["ingress"])
    eg = p["spec"]["egress"]
    assert any("kube-apiserver" in r.get("toEntities", []) for r in eg)
    assert any(53 in _ports(r) for r in eg)
    assert any(_ports(r) == {5432} for r in eg)
    assert any(r.get("toEndpoints", [{}])[0].get("matchLabels", {}).get(NS_KEY)
               == "keycloak" for r in eg)


def test_placeholders_marked():
    txt = (COMPONENT / "ccnp-styx.yaml").read_text()
    assert txt.count("PLACEHOLDER(#") >= 2
    assert "PLACEHOLDER(#" in (COMPONENT / "ccnp-traefik.yaml").read_text()


def test_kustomization_lists_every_ccnp_file():
    comp = yaml.safe_load((COMPONENT / "kustomization.yaml").read_text())
    files = {f.name for f in COMPONENT.glob("ccnp-*.yaml")}
    assert {r for r in comp["resources"] if r.startswith("ccnp-")} == files
