"""Same-repo CI runs on homelab; fork PRs stay on GitHub-hosted runners."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXPR = "${{ github.event.pull_request.head.repo.fork && 'ubuntu-latest' || 'homelab' }}"


def _find(name: str) -> Path:
    for d in ("wq-workflows", ".github/workflows"):
        p = ROOT / d / name
        if p.exists() and EXPR in p.read_text():
            return p
    pytest.fail(f"{name}: no copy uses the fork-safe runs-on expression")


@pytest.mark.parametrize("name", ["wq-ci.yml", "dependabot-automerge.yml"])
def test_fork_safe_runs_on(name):
    text = _find(name).read_text()
    assert "runs-on: ubuntu-latest" not in text


def test_dependabot_automerge_not_pull_request_target():
    text = (ROOT / "wq-workflows" / "dependabot-automerge.yml").read_text()
    assert "pull_request_target" not in text
    assert "on: pull_request" in text
