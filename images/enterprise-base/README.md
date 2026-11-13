# enterprise-base

Rootless Ubuntu 24.04 base with Selkies + pixelflux (ADR-0057). Replaces the third-party
desktop base for enterprise desktops.

- Build args: `UBUNTU_DIGEST` (TODO: real digest), `SELKIES_VERSION`, `PIXELFLUX_VERSION`, `PCMFLUX_VERSION`.
- Runs as `1000:1000`; no sudo, no setuid helpers.
- Entrypoint `styx-start` runs Selkies on `127.0.0.1:8082` and the Styx gateway on `8080` (the only exposed port). Env: `STYX_LOCK_IDLE_S` (default 900), `STYX_UNLOCK_KEY` (required; empty exits non-zero), `STYX_UNLOCK_URL`, `STYX_INSTANCE_ID`. Build from the repo root: `docker build -f images/enterprise-base/Dockerfile .`
