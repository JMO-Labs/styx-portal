# enterprise-base

Rootless Ubuntu 24.04 base with Selkies + pixelflux (ADR-0057). Replaces the third-party
desktop base for enterprise desktops.

- Build args: `UBUNTU_DIGEST` (TODO: real digest), `SELKIES_VERSION`, `PIXELFLUX_VERSION`, `PCMFLUX_VERSION`.
- Runs as `1000:1000`; no sudo, no setuid helpers.
- Entrypoint `styx-start` serves Selkies on port 8082; health URL `http://localhost:8082/`.
- Smart-card: ships pcscd + virtualsmartcard vpcd (`VSMARTCARD_VERSION`, default 0.10) and `styx-card-relay`
  (built from `smartcard/`; build with `--build-context smartcard=smartcard`). With `SMARTCARD_ENABLED=true`,
  `styx-start` starts pcscd and the relay (port `SMARTCARD_RELAY_PORT`, default 8090) before Selkies.
  Requires `STYX_INSTANCE_ID`. Backend routes `/w/<sub>/smartcard` to the relay when `SMARTCARD_ENABLED=true`.
