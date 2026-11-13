# ADR-0076: Fast launch: pre-pull signed digests

- Status: Proposed
- Date: 2026-11-13
- Decision ID: D75
- Related controls: CM-2, CM-3, SC-5, CP-2
- Refines: ADR-0046, ADR-0030, ADR-0069

## Context

ADR-0046 (D46) sets the launch goal: p50 ≤ 5 s, p95 < 10 s. This records how the implementation meets it. (The ticket proposed number 0070; taken by DLP, so this is 0076.) Phases and measurement: [launch-profile.md](../launch-profile.md).

## Decision

1. **Pre-pull signed digests on all nodes.** `k8s_prepull.py` syncs every `PREPULL_INTERVAL_S` (default 3600) so each worker already holds the cosign-verified golden-image digest. Only digests that passed signature verification are pulled (ADR-0069).
2. **A new digest becomes the default only after pre-pull ready.** Launch keeps the previous digest until the pre-pull reports ready on the nodes; then it switches. A launch never waits for a cold image pull on a new digest.
3. **Home mounted at pod start.** The user's CephFS home is a volume of the desktop pod (as the user's POSIX UID, ADR-0052, ADR-0066), not attached after start.
4. **No warm pools.** Per-image warm pools are dropped from v1 (D46). Optional later: per-user scheduled pre-warm.
5. **p95 ≥ 10 s alert.** A recording rule computes launch p95; an alert fires when it is ≥ 10 s (`StyxLaunchP95High` in `deploy/k8s/slo-rules.yaml`, [slo.md](../../operate/slo.md)).
6. **kind benchmark.** `scripts/kind/30-launch-bench.sh` runs a pre-pulled pod launch on kind and reports p50 and p95. It shows the pre-pull effect, not production numbers.

## Top three latency contributors

| # | Contributor | What was done |
|---|---|---|
| 1 | `ready_s`: scheduling, image pull, container start, readiness | Pre-pull on all nodes (1), new digest gated on pre-pull ready (2), home mounted at pod start (3). |
| 2 | `digest_s`: synchronous Harbor lookup (cold, up to 5 s) | Cached per ref for `DIGEST_CACHE_S` (60 s); errors not cached. |
| 3 | `apply_s`: sequential API round trips per object | Measured by `launch_phases` log line; not optimised (tens to hundreds of ms). |

## Alternatives considered

- Warm pools: idle capacity cost and per-user state complexity (D46).
- Pull on launch: breaks the p95 ceiling on large images.
- Switch digest at once on publish: first launches after a nightly rebuild would pay a cold pull.

## Consequences

Positive: launches avoid image pulls; the SLO is alerting-backed; a nightly rebuild does not slow users.

Negative: every worker keeps the current and previous golden images on disk; a new digest reaches users up to one pre-pull cycle later (24 h critical-CVE recycle, ADR-0030, still applies).
