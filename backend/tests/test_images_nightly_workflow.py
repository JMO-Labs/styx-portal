"""Static checks for the nightly desktop image supply-chain workflow (ADR-0029)."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = [
    ROOT / ".github/workflows/images-nightly.yml",
    ROOT / "wq-workflows/images-nightly.yml",  # pending owner promotion
]


def _load() -> dict:
    path = next(p for p in CANDIDATES if p.exists())
    data = yaml.safe_load(path.read_text())
    data["on"] = data.pop(True, data.get("on"))  # YAML parses `on` as True
    return data


def _steps() -> list[dict]:
    jobs = _load()["jobs"]
    return [s for j in jobs.values() for s in j["steps"]]


def _runs() -> str:
    return "\n".join(s.get("run", "") for s in _steps())


def test_triggers_schedule_and_dispatch():
    on = _load()["on"]
    assert on["schedule"][0]["cron"]
    assert "workflow_dispatch" in on


def test_builds_desktop_image_and_pushes_by_digest():
    steps = _steps()
    build = [s for s in steps if str(s.get("uses", "")).startswith("docker/build-push-action")]
    assert build and build[0]["with"]["context"] == "images/desktop"
    assert str(build[0]["with"]["push"]).lower() == "true"
    assert build[0].get("id")
    assert "digest" in str(steps)


def test_trivy_fails_on_high_critical():
    trivy = [s for s in _steps() if str(s.get("uses", "")).startswith("aquasecurity/trivy-action")]
    assert trivy
    w = trivy[0]["with"]
    assert str(w["exit-code"]) == "1"
    assert w["severity"] == "HIGH,CRITICAL"
    assert "trivyignores" in w and ".trivyignore" in str(w["trivyignores"])


def test_cosign_sign_and_attest_cyclonedx():
    runs = _runs()
    assert re.search(r"cosign sign\b", runs)
    assert re.search(r"cosign attest\b.*--type cyclonedx", runs, re.S)
    assert "@${{ steps." in runs or "@$DIGEST" in runs or "@${DIGEST}" in runs


def test_secrets_not_hardcoded():
    text = next(p for p in CANDIDATES if p.exists()).read_text()
    assert "secrets.HARBOR" in text and "secrets.COSIGN" in text
    assert "BEGIN" not in text


def test_all_actions_pinned_by_sha():
    uses = [s["uses"] for s in _steps() if "uses" in s]
    assert uses
    for u in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", u), u
