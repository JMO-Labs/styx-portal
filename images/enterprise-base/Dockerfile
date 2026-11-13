# Enterprise rootless Selkies/pixelflux base image (ADR-0057).
# TODO: pin UBUNTU_DIGEST to the real ubuntu:24.04 manifest digest
# (`docker buildx imagetools inspect ubuntu:24.04`); pass --build-arg in CI.
ARG UBUNTU_DIGEST=sha256:0000000000000000000000000000000000000000000000000000000000000000

# Relay binary (static), built from smartcard/ (build context = images/enterprise-base,
# so CI passes `--build-context smartcard=smartcard`).
FROM golang:1.22-bookworm AS relay
WORKDIR /src
COPY --from=smartcard . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/styx-card-relay ./cmd/styx-card-relay

# virtualsmartcard vpcd (pcscd IFD driver), pinned upstream release.
FROM ubuntu:24.04@${UBUNTU_DIGEST} AS vpcd
ARG VSMARTCARD_VERSION=0.10
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl build-essential autoconf automake libtool pkg-config \
        help2man gengetopt libpcsclite-dev \
    && curl -fsSL "https://github.com/frankmorgner/vsmartcard/releases/download/virtualsmartcard-${VSMARTCARD_VERSION}/virtualsmartcard-${VSMARTCARD_VERSION}.tar.gz" \
        | tar -xz -C /tmp \
    && cd "/tmp/virtualsmartcard-${VSMARTCARD_VERSION}" \
    && ./configure --prefix=/usr --sysconfdir=/etc && make -j"$(nproc)" \
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
        ca-certificates curl python3 python3-pip python3-venv \
        pcscd libpcsclite1 xwayland labwc pulseaudio libgl1 libegl1 libopus0 fonts-dejavu-core \
    && { find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true; } \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/selkies \
    && /opt/selkies/bin/pip install --no-cache-dir \
        "selkies==${SELKIES_VERSION}" \
        "pixelflux==${PIXELFLUX_VERSION}" \
        "pcmflux==${PCMFLUX_VERSION}"

# Ubuntu 24.04 ships uid 1000 ("ubuntu"); replace it with our user.
RUN userdel -r ubuntu 2>/dev/null || true \
    && groupadd -g 1000 styx \
    && useradd -u 1000 -g 1000 -m -d /home/styx -s /bin/bash styx

# pcscd runs as 1000:1000; it needs a writable socket dir.
RUN install -d -o 1000 -g 1000 /run/pcscd

COPY --from=vpcd /out/ /
COPY --from=relay /out/styx-card-relay /usr/local/bin/styx-card-relay
COPY --from=smartcard --chmod=0644 apdu-allowlist.yaml /etc/styx/apdu-allowlist.yaml
COPY --chmod=0755 root/usr/local/bin/styx-start /usr/local/bin/styx-start

EXPOSE 8082
# Health URL: http://localhost:8082/
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS -o /dev/null http://127.0.0.1:8082/ || exit 1

USER 1000:1000
WORKDIR /home/styx
ENTRYPOINT ["/usr/local/bin/styx-start"]
