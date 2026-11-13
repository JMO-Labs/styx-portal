# Enterprise rootless Selkies/pixelflux base image (ADR-0057).
# TODO: pin UBUNTU_DIGEST to the real ubuntu:24.04 manifest digest
# (`docker buildx imagetools inspect ubuntu:24.04`); pass --build-arg in CI.
ARG UBUNTU_DIGEST=sha256:0000000000000000000000000000000000000000000000000000000000000000
FROM ubuntu:24.04@${UBUNTU_DIGEST}

ARG SELKIES_VERSION=2.2.0
ARG PIXELFLUX_VERSION=2.2.2
ARG PCMFLUX_VERSION=2.2.1

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/home/styx \
    SELKIES_PORT=8082

# No sudo, no setuid helpers are installed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl patch python3 python3-pip python3-venv \
        xwayland labwc pulseaudio libgl1 libegl1 libopus0 fonts-dejavu-core \
    && { find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true; } \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/selkies \
    && /opt/selkies/bin/pip install --no-cache-dir \
        "selkies==${SELKIES_VERSION}" \
        "pixelflux==${PIXELFLUX_VERSION}" \
        "pcmflux==${PCMFLUX_VERSION}" \
        aiohttp yarl multidict

# Build context is the repo root (docker build -f images/enterprise-base/Dockerfile .).
# Fails the build if any patch in the series does not apply.
COPY patches/selkies/ /opt/selkies-patches/
COPY --chmod=0755 scripts/apply_selkies_patches.sh /usr/local/bin/apply_selkies_patches.sh
RUN SELKIES_PATCH_DIR=/opt/selkies-patches /usr/local/bin/apply_selkies_patches.sh \
        "$(/opt/selkies/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && rm -rf /opt/selkies-patches /usr/local/bin/apply_selkies_patches.sh

# Ubuntu 24.04 ships uid 1000 ("ubuntu"); replace it with our user.
RUN userdel -r ubuntu 2>/dev/null || true \
    && groupadd -g 1000 styx \
    && useradd -u 1000 -g 1000 -m -d /home/styx -s /bin/bash styx

# Styx gateway (lock enforcement) and the agent modules it imports.
COPY agent/gateway.py agent/gateway_dlp.py agent/gateway_html.py agent/gateway_idlelock.py \
     agent/gateway_lock.py agent/gateway_report.py agent/gateway_webrtc.py agent/gateway_ws.py \
     agent/favicon.py agent/refit.py agent/codecpref.py agent/gamemode.py agent/seat_scale.py \
     agent/session_events.py agent/viewers.py agent/portal_api.py /opt/styx/

COPY --chmod=0755 images/enterprise-base/root/usr/local/bin/styx-start /usr/local/bin/styx-start

EXPOSE 8080
# Gateway on 8080 proxies Selkies on loopback 8082.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -s -o /dev/null http://127.0.0.1:8080/ || exit 1

USER 1000:1000
WORKDIR /home/styx
ENTRYPOINT ["/usr/local/bin/styx-start"]
