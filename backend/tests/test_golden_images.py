"""Static checks for golden image Dockerfiles (ADR-0028)."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "images" / "golden"
NAMES = ["base-office", "developer", "browser-only"]


def _lines(name):
    text = (ROOT / name / "Dockerfile").read_text()
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


@pytest.mark.parametrize("name", NAMES)
def test_inherits_base_image(name):
    lines = _lines(name)
    assert lines[0] == "ARG BASE_IMAGE=styx-enterprise-base:latest"
    assert "FROM ${BASE_IMAGE}" in lines


@pytest.mark.parametrize("name", NAMES)
def test_final_user_non_root(name):
    users = [ln for ln in _lines(name) if ln.startswith("USER ")]
    assert users and users[-1] == "USER 1000:1000"
    assert not re.match(r"USER\s+(root|0)\b", users[-1])


@pytest.mark.parametrize("name", NAMES)
def test_no_linuxserver(name):
    for p in (ROOT / name).rglob("*"):
        if p.is_file():
            assert "linuxserver" not in p.read_text().lower()


def test_browser_policy_homepage():
    pol = next((ROOT / "browser-only" / "root").rglob("policies.json"))
    assert "https://portal.office365.us" in pol.read_text()


def test_package_contents():
    t = {n: (ROOT / n / "Dockerfile").read_text() for n in NAMES}
    assert not re.search(r"\bsnap (install|download)|snapd", t["browser-only"])
    assert "firefox" in t["browser-only"] and "firefox" in t["base-office"]
    assert "evince" in t["base-office"] or "okular" in t["base-office"]
    for pkg in ("git", "code"):
        assert re.search(rf"\b{pkg}\b", t["developer"])
    assert "terminal" in t["developer"]
