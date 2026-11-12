# Enterprise images

The enterprise profile runs desktops from a rootless base image plus three golden images.
Decisions: [ADR-0067](../enterprise/adr/0067-enterprise-image-layout-and-cpu-tier-overrides.md),
[ADR-0057](../enterprise/adr/0057-own-rootless-selkies-pixelflux-base-image.md),
[ADR-0028](../enterprise/adr/0028-golden-images-3-5-ubuntu-based-images-built-in-ci.md) (see the [ADR index](../enterprise/adr/README.md)).

| Path | What |
|---|---|
| `images/enterprise-base` | Ubuntu 24.04, Selkies + pixelflux, runs as `1000:1000`, port 8082 |
| `images/golden/browser-only` | Base + Firefox with the M365 GCC High homepage policy |
| `images/golden/base-office` | Browser-only + Evince |
| `images/golden/developer` | Base + git, xfce4-terminal, VS Code |

## Build locally

Needs Docker. Resolve the real Ubuntu digest first (the Dockerfile default is a placeholder):

```bash
DIGEST=$(docker buildx imagetools inspect ubuntu:24.04 --format '{{json .Manifest.Digest}}' | tr -d '"')
docker build --build-arg "UBUNTU_DIGEST=$DIGEST" -t styx-enterprise-base:latest images/enterprise-base
```

Then a golden image on top of it:

```bash
docker build --build-arg BASE_IMAGE=styx-enterprise-base:latest \
  -t styx-golden-developer:latest images/golden/developer
```

Swap `developer` for `browser-only` or `base-office`. Pin versions with the
`SELKIES_VERSION`, `PIXELFLUX_VERSION` and `PCMFLUX_VERSION` build args.

## Kind smoke test

`scripts/kind/10-enterprise-base-smoke.sh` builds the base, loads it into the `spike` kind
cluster, runs it under Pod Security `baseline`, and checks that the container UID is 1000 and
Selkies answers HTTP 200 on port 8082. CI runs it as the `kind-spike` check. Locally,
create the cluster as described in `scripts/kind/README.md`, then run the script from the
repo root.

## CPU-tier settings and group overrides

Global launch defaults (ADR-0031) are settings, shown in [Settings](settings.md):

| Setting | Default |
|---|---|
| `CPU_TIER_RESOLUTION` | `1920x1080` |
| `CPU_TIER_FPS` | `30` |
| `CPU_TIER_HIDPI` | `false` |
| `CPU_TIER_CPU` | `3` |
| `CPU_TIER_MEMORY` | `4Gi` |

A group can override any field (`tier_resolution`, `tier_fps`, `tier_hidpi`, `tier_cpu`,
`tier_memory`). Empty fields use the global default.

**A user in several groups gets the highest value per field:** highest cpu, memory and fps,
the resolution with the most pixels, and HiDPI if any group enables it. To lower someone's
tier, remove them from the group that grants more.
