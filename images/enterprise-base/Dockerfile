# Enterprise rootless Selkies/pixelflux base image (ADR-0057).
# TODO: pin UBUNTU_DIGEST to the real ubuntu:24.04 manifest digest
# (`docker buildx imagetools inspect ubuntu:24.04`); pass --build-arg in CI.
ARG UBUNTU_DIGEST=sha256:0000000000000000000000000000000000000000000000000000000000000000

# Relay binary (static), built from smartcard/ (build context = repo root).
FROM golang:1.22-bookworm AS relay
WORKDIR /src
COPY smartcard/ .
# go.sum is not committed yet: resolve it at build time (TODO styx-portal#325: commit go.sum, build -mod=readonly).
RUN go mod tidy && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/styx-card-relay ./cmd/styx-card-relay

# virtualsmartcard vpcd (pcscd IFD driver), pinned upstream release.
FROM ubuntu:24.04@${UBUNTU_DIGEST} AS vpcd
# configure prepends --prefix to pcscd's dirs, so pin them explicitly.
# 0.10 is the latest release that ships a source tarball (0.11 only has zips).
ARG VSMARTCARD_VERSION=0.10
ARG VSMARTCARD_SHA256=1401a441250f3da0b71fa440a252b37907487a0326abec71a33b6cf05f247623
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl build-essential autoconf automake libtool pkg-config \
        help2man gengetopt libpcsclite-dev python3 \
    && curl -fsSL -o /tmp/vsmartcard.tar.gz \
        "https://github.com/frankmorgner/vsmartcard/releases/download/virtualsmartcard-${VSMARTCARD_VERSION}/virtualsmartcard-${VSMARTCARD_VERSION}.tar.gz" \
    && echo "${VSMARTCARD_SHA256}  /tmp/vsmartcard.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/vsmartcard.tar.gz -C /tmp \
    && cd "/tmp/virtualsmartcard-${VSMARTCARD_VERSION}" \
    && ./configure --prefix=/usr --sysconfdir=/etc \
        --enable-serialconfdir=/etc/reader.conf.d \
        --enable-serialdropdir=/usr/lib/pcsc/drivers/serial \
    && make -j"$(nproc)" \
    && make install DESTDIR=/out

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
        pcscd libpcsclite1 xwayland labwc pulseaudio libgl1 libegl1 libopus0 fonts-dejavu-core \
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

# pcscd runs as 1000:1000; it needs a writable socket dir.
RUN install -d -o 1000 -g 1000 /run/pcscd

COPY --from=vpcd /out/ /
COPY --from=relay /out/styx-card-relay /usr/local/bin/styx-card-relay
COPY --chmod=0644 smartcard/apdu-allowlist.yaml /etc/styx/apdu-allowlist.yaml

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
