# Service level objectives

Three SLOs are defined in `deploy/k8s/slo-rules.yaml` (recording rules and burn-rate alerts). Alert handling is in the [alert runbook](alert-runbook.md).

## Scope and exclusions

- **Business hours:** Mon-Fri 07:00-18:00 `America/New_York` by default. The `styx_slo_business_hours` gauge is 1 inside the window; if it is absent the SLO stays in scope (fail-safe).
- **Maintenance:** the monthly announced maintenance window is excluded (ADR-0008). `styx_maintenance_active == 1` removes scope.
- Both are combined in `styx:slo_in_scope`; samples outside scope are not counted.

## Definitions

| SLO | SLI (good / total) | Target | Window | Error budget |
|---|---|---|---|---|
| Availability | blackbox `probe_success` over login, portal and services (`deploy/k8s/probes.yaml`) | 99.9% | calendar month, in-scope hours | 0.001 |
| Launch | launches with `outcome="ok"` finishing in <= 10 s (`styx_launch_duration_seconds`) | 95% | rolling, in-scope hours | 0.05 |
| Stream RTT | RTT samples <= 80 ms (`styx_stream_rtt_seconds`) | 95% | rolling, in-scope hours | 0.05 |

Launch goal: p50 <= 5 s (ticket alert `StyxLaunchP50AboveGoal`), ceiling p95 < 10 s.

**RTT is network round trip time between browser and stream, not input-to-photon latency.** It excludes capture, encode, decode and display. Input-to-photon is measured separately by the D47 load test.

## Budget math

In-scope time is about 22 days x 11 h = 242 h per month. The availability budget is 0.1% of that: 242 h x 60 min x 0.001 = about 14.5 min per month.

## Burn-rate alerts

Multi-window, multi-burn-rate (Google SRE workbook). Both windows must exceed `factor x budget`.

| Severity | Burn rate | Long / short window | `for` |
|---|---|---|---|
| page | 14.4x | 1h / 5m | 2m |
| page | 6x | 6h / 30m | 2m |
| ticket | 3x | 1d / 2h | 15m |
| ticket | 1x | 3d / 6h | 15m |

Launch alerts also need more than 5 launches in the long window.

## Capacity headroom

One desktop slot = 3 CPU + 4 GiB (ADR-0031). Warning (ticket) when free slots drop below the largest node (N+1); critical (page) when free slots are below 10% of peak (`styx_capacity_peak_desktops`, default 200).

## Watchdog

The always-firing Watchdog alert is forwarded to the portal. If none arrives for 10 minutes the portal flags `monitoring_silent` (`/api/ops/alerts`): monitoring itself is down and no other alert can be trusted.
