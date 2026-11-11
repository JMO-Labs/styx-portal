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
