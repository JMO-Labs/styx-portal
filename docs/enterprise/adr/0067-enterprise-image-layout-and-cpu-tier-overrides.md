# ADR-0067: Enterprise image layout and CPU-tier overrides

- Status: Proposed
- Date: 2026-11-12
- Decision ID: D66
- Related controls: CM-2, CM-6, CM-7, SA-10

## Context

ADR-0028 (golden images), ADR-0031 (CPU-tier caps), ADR-0057 (own rootless base) and
ADR-0058 (Selkies patch set) were implemented across several tickets. This ADR records the
resulting layout and the one rule for users in several groups.

Note: the ticket suggested 0062; that number is taken, so the next free one (0067) is used.

## Decision

- **Image paths.** The shared base is `images/enterprise-base`; golden images are
  `images/golden/<name>` (`browser-only`, `base-office`, `developer`). Each golden image
  inherits the base through `ARG BASE_IMAGE`. The homelab `images/desktop` is not used by
  the enterprise profile.
- **UID 1000.** The base and every golden image run as `1000:1000`: no sudo, no setuid
  helpers. Per-user POSIX UIDs for homes come from the pod security context (ADR-0066).
- **Patch-set layout.** Selkies patches (ADR-0058) are kept as numbered files under
  `docs/upstream/`, one per change, each offered upstream first. The base image pins
  Selkies, pixelflux and pcmflux versions by build arg; patches are applied on top of
  those pins, never by forking.
- **CPU-tier settings.** Global defaults are the `CPU_TIER_*` settings (resolution, fps,
  HiDPI, cpu, memory; ADR-0031). A group may override any field.
- **Multi-group rule: highest wins.** A user in several groups gets, per field, the most
  generous value: highest cpu, memory and fps, the resolution with the most pixels, HiDPI if
  any group enables it. Fields no group sets fall back to the global default.

## Alternatives considered

- First or last matching group wins: depends on ordering, surprising to admins.
- Lowest wins: a restrictive group would silently downgrade users granted more elsewhere.
- Fork Selkies: rejected by ADR-0003.

## Consequences

Positive:

- One documented layout for audit (CM-2, CM-6, CM-7) and a deterministic override rule.

Negative:

- A user cannot be capped by joining a group; restrict by removing the generous group.
- Patches need rebasing on each Selkies bump.
