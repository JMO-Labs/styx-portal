"""Static checks for the enterprise rootless Selkies base image (ADR-0057)."""

import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[2] / "images" / "enterprise-base"
DOCKERFILE = (BASE / "Dockerfile").read_text()


def _instructions():
    return [ln.strip() for ln in DOCKERFILE.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def test_pinned_digest_arg_and_from():
    assert re.search(r"^ARG UBUNTU_DIGEST=\S+", DOCKERFILE, re.M)
    assert "FROM ubuntu:24.04@${UBUNTU_DIGEST}" in DOCKERFILE


def test_final_user_numeric_non_root():
    users = [i.split(None, 1)[1] for i in _instructions() if i.startswith("USER ")]
    assert users[-1] == "1000:1000"


def test_no_linuxserver():
    assert "linuxserver" not in DOCKERFILE.lower()
    for p in BASE.rglob("*"):
        if p.is_file():
            assert "linuxserver" not in p.read_text(errors="ignore").lower()


def test_pinned_version_args():
    for name in ("SELKIES_VERSION", "PIXELFLUX_VERSION"):
        assert re.search(rf"^ARG {name}=\d+\.\d+\.\d+", DOCKERFILE, re.M)
        assert f"${{{name}}}" in DOCKERFILE


def test_no_sudo_or_setuid():
    assert not re.search(r"\bsudo\b", "\n".join(_instructions()))
    assert "chmod u+s" not in DOCKERFILE and "chmod +s" not in DOCKERFILE


def test_healthcheck_and_entrypoint():
    assert any(i.startswith("HEALTHCHECK") for i in _instructions())
    script = BASE / "root/usr/local/bin/styx-start"
    assert script.is_file()
    assert "8082" in script.read_text()
    assert "ENTRYPOINT" in DOCKERFILE and "styx-start" in DOCKERFILE
