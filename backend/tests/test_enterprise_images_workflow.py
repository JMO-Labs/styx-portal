"""Static checks for the enterprise image CI workflow (ADR-0028/0057, #150).

The file lives in wq-workflows/ until the owner promotes it to .github/workflows/.
"""
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
NAME = "enterprise-images.yml"
GOLDEN = ["base-office", "developer", "browser-only"]


def _path():
    for d in (".github/workflows", "wq-workflows"):
        p = REPO / d / NAME
        if p.exists():
            return p
    pytest.fail(f"{NAME} not found")


@pytest.fixture(scope="module")
def wf():
    text = _path().read_text()
    return text, yaml.safe_load(text)


def test_triggers_on_enterprise_image_paths(wf):
    _, doc = wf
    on = doc.get("on", doc.get(True))
    for ev in ("push", "pull_request"):
        assert on[ev]["branches"] == ["enterprise"]
        assert set(on[ev]["paths"]) >= {"images/enterprise-base/**", "images/golden/**", "smartcard/**"}


def test_read_only_permissions_and_no_push(wf):
    text, doc = wf
    assert doc["permissions"] == {"contents": "read"}
    assert "docker push" not in text
    assert "login-action" not in text
    assert not re.search(r"push:\s*true", text)


def test_actions_pinned_by_sha(wf):
    text, _ = wf
    uses = re.findall(r"uses:\s*(\S+)", text)
    assert uses
    for u in uses:
        assert re.search(r"@[0-9a-f]{40}$", u), u


def _steps(doc):
    return [s for job in doc["jobs"].values() for s in job["steps"]]


def test_base_built_with_pinned_digest_before_golden(wf):
    _, doc = wf
    runs = [s.get("run", "") for s in _steps(doc)]
    base_idx = next(i for i, r in enumerate(runs) if "images/enterprise-base" in r and "docker build" in r)
    assert "UBUNTU_DIGEST=" in runs[base_idx]
    assert any("imagetools inspect ubuntu:24.04" in r for r in runs[:base_idx])
    for name in GOLDEN:
        idx = next(i for i, r in enumerate(runs) if f"images/golden/{name}" in r)
        assert idx > base_idx
        assert "--build-arg BASE_IMAGE=" in runs[idx]


def test_failures_fail_job(wf):
    _, doc = wf
    for job in doc["jobs"].values():
        assert not job.get("continue-on-error")
        for s in job["steps"]:
            assert not s.get("continue-on-error")
