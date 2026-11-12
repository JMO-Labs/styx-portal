# base-office golden image (ADR-0028). Firefox from the Mozilla apt repo (deb, not snap).
ARG BASE_IMAGE=styx-enterprise-base:latest
FROM ${BASE_IMAGE}

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends gnupg wget ca-certificates \
    && install -d -m 0755 /etc/apt/keyrings \
    && wget -qO- https://packages.mozilla.org/apt/repo-signing-key.gpg > /etc/apt/keyrings/packages.mozilla.org.asc \
    && echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" > /etc/apt/sources.list.d/mozilla.list \
    && printf "Package: *\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n" > /etc/apt/preferences.d/mozilla \
    && apt-get update
RUN apt-get install -y --no-install-recommends firefox evince \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY root/ /

USER 1000:1000
