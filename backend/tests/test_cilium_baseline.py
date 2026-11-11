"""Vendored Cilium CRD schemas for offline kubeconform validation."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

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
