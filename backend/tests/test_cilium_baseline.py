"""Vendored Cilium CRD schemas for offline kubeconform validation."""

import json
from pathlib import Path

SCHEMAS = (
    Path(__file__).resolve().parents[2]
    / "deploy/k8s/components/cilium-baseline/schemas"
)


def test_kubeconform_schemas_vendored():
    for name in ("ciliumnetworkpolicy_v2.json", "ciliumclusterwidenetworkpolicy_v2.json"):
        data = json.loads((SCHEMAS / name).read_text())
        assert data["properties"]["spec"]
    assert "1.20.4" in (SCHEMAS / "README.md").read_text()
