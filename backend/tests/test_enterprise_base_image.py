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


def test_start_script_has_display_source_and_port():
    text = (BASE / "root/usr/local/bin/styx-start").read_text()
    assert "--wayland=true" in text
    assert "8082" in text
    # selkies 2.x binds loopback by default; the gateway is the public face.
    assert "--public" not in text
    assert "--addr" not in text


def test_dockerfile_copies_gateway_modules_and_deps():
    for mod in ("gateway.py", "gateway_lock.py", "gateway_idlelock.py", "portal_api.py", "viewers.py"):
        assert mod in DOCKERFILE
    assert "aiohttp" in DOCKERFILE
    assert "EXPOSE 8080" in DOCKERFILE and "EXPOSE 8082" not in DOCKERFILE


def test_start_script_runs_gateway_in_front():
    text = (BASE / "root/usr/local/bin/styx-start").read_text()
    for needle in ("127.0.0.1", "STYX_LOCK_IDLE_S:-900", "STYX_UNLOCK_KEY", "STYX_UNLOCK_URL",
                   "STYX_INSTANCE_ID", "gateway.py", "8080"):
        assert needle in text


def _run_start(env):
    import subprocess
    script = BASE / "root/usr/local/bin/styx-start"
    return subprocess.run(["sh", str(script)], env={"PATH": "/usr/bin:/bin", **env},
                          capture_output=True, text=True, timeout=10)


def test_start_refuses_without_unlock_key():
    for env in ({}, {"STYX_UNLOCK_KEY": ""}):
        r = _run_start(env)
        assert r.returncode != 0
        assert "STYX_UNLOCK_KEY" in r.stderr


def test_apt_run_does_not_swallow_install_failure():
    run = next(i for i in DOCKERFILE.split("\n\n") if "apt-get install" in i)
    assert "apt-get install" in run
    assert "{ find" in run and "|| true; }" in run
    assert "-exec chmod a-s {} + 2>/dev/null || true \\" not in run
