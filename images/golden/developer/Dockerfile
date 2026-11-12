# developer golden image (ADR-0028). Firefox from the Mozilla apt repo (deb, not snap).
ARG BASE_IMAGE=styx-enterprise-base:latest
FROM ${BASE_IMAGE}

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends git xfce4-terminal wget gpg ca-certificates \
    && install -d -m 0755 /etc/apt/keyrings \
    && wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /etc/apt/keyrings/microsoft.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/code stable main" > /etc/apt/sources.list.d/vscode.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY root/ /

USER 1000:1000
