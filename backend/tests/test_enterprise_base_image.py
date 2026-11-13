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
    # selkies 2.x: --addr is loopback-only by default; --public binds all
    # interfaces and is mutually exclusive with --addr.
    assert "--public" in text
    assert "--addr" not in text


def test_apt_run_does_not_swallow_install_failure():
    # Runtime stage only: builder stages (relay, vpcd) may install freely.
    runtime = DOCKERFILE.split("\nFROM ")[-1]
    run = next(i for i in runtime.split("\n\n") if "apt-get install" in i)
    assert "apt-get install" in run
    assert "{ find" in run and "|| true; }" in run
    assert "-exec chmod a-s {} + 2>/dev/null || true \\" not in run


def test_vsmartcard_tarball_checksum_verified():
    assert re.search(r"^ARG VSMARTCARD_SHA256=[0-9a-f]{64}$", DOCKERFILE, re.M)
    assert 'echo "${VSMARTCARD_SHA256}  ' in DOCKERFILE and "sha256sum -c -" in DOCKERFILE
    assert not re.search(r"curl[^\n]*vsmartcard[^\n]*\n[^\n]*\|\s*tar", DOCKERFILE)


def test_smartcard_smoke_avoids_procps_and_uses_ulong():
    smoke = (BASE.parents[1] / "scripts/kind/20-smartcard-smoke.sh").read_text()
    assert "pgrep" not in smoke
    assert "/proc/[0-9]*/comm" in smoke
    assert "c_uint32" not in smoke and "ctypes.c_ulong(0)" in smoke
    assert "SCardListReaders.argtypes" in smoke and "SCardEstablishContext.argtypes" in smoke


def test_dockerfile_applies_selkies_patches_after_pip_install():
    assert "COPY patches/selkies/ /opt/selkies-patches/" in DOCKERFILE
    assert "apply_selkies_patches.sh" in DOCKERFILE
    assert DOCKERFILE.index("pip install") < DOCKERFILE.index("apply_selkies_patches.sh")


def test_patch_tool_installed_for_selkies_series():
    apt = re.search(r"apt-get install[^&]*", DOCKERFILE).group(0)
    assert re.search(r"\bpatch\b", apt)


def test_series_skips_patches_merged_upstream():
    """Patches whose note says 'not kept' ship in the pinned wheels; applying them fails the build."""
    root = BASE.parents[1]
    series = (root / "patches/selkies/series").read_text().splitlines()
    names = [n.strip() for n in series if n.strip() and not n.strip().startswith("#")]
    for name in names:
        note = (root / "docs/upstream" / name.replace(".patch", ".md")).read_text()
        assert "not kept" not in note, f"{name} is merged upstream; drop it from series"


def test_series_patches_touch_only_installed_package_paths():
    """The script patches installed wheels; Rust sources (pixelflux/src/*.rs) are not shipped."""
    root = BASE.parents[1] / "patches/selkies"
    series = (root / "series").read_text().splitlines()
    names = [n.strip() for n in series if n.strip() and not n.strip().startswith("#")]
    for name in names:
        targets = re.findall(r"^\+\+\+ b/(\S+)", (root / name).read_text(), re.M)
        assert targets, f"{name} has no targets"
        bad = [t for t in targets if t.endswith(".rs") or t.startswith("pixelflux/src/")]
        assert not bad, f"{name} edits source not in the installed wheel: {bad}"
