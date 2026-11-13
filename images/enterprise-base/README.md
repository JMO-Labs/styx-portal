# enterprise-base

Rootless Ubuntu 24.04 base with Selkies + pixelflux (ADR-0057). Replaces the third-party
desktop base for enterprise desktops.

- Build args: `UBUNTU_DIGEST` (TODO: real digest), `SELKIES_VERSION`, `PIXELFLUX_VERSION`, `PCMFLUX_VERSION`.
- Runs as `1000:1000`; no sudo, no setuid helpers.
- Entrypoint `styx-start` serves Selkies on port 8082; health URL `http://localhost:8082/`.
- Patches: after `pip install`, `scripts/apply_selkies_patches.sh` applies `patches/selkies/series`
  (in order, `patch -p1 --forward`) to the venv site-packages; the build fails if any patch does not apply.
  Build from the repo root: `docker build -f images/enterprise-base/Dockerfile .`.
