# enterprise-base

Rootless Ubuntu 24.04 base with Selkies + pixelflux (ADR-0057). Replaces the third-party
desktop base for enterprise desktops.

- Build args: `UBUNTU_DIGEST` (TODO: real digest), `SELKIES_VERSION`, `PIXELFLUX_VERSION`, `PCMFLUX_VERSION`.
- Runs as `1000:1000`; no sudo, no setuid helpers.
- Entrypoint `styx-start` serves Selkies on port 8082; health URL `http://localhost:8082/`.
