# Alert runbook

One section per alert. Definitions: [SLOs](slo.md). Rules: `deploy/k8s/slo-rules.yaml`, `deploy/k8s/prometheusrule.yaml`.

**Escalation path (all alerts):** on-call engineer -> platform owner -> project maintainers. Page alerts: escalate if not mitigated in 30 min. Ticket alerts: handle next business day. Announce in the ops channel before escalating.

## StyxAvailabilityBurnRatePage

**Means:** probes are failing fast enough to burn the 99.9% monthly budget in hours (>14.4x over 1h/5m, or >6x over 6h/30m).
**First checks:**
1. Prometheus: `probe_success == 0` to see which probe fails.
2. `kubectl -n styx get pods`; backend, Traefik and Authentik/OIDC ready?
3. Recent deploys or node events; check the maintenance flag (`styx_maintenance_active`).
**Escalate:** platform owner if no cause in 15 min; roll back the last change first.

## StyxAvailabilityBurnRateTicket

**Means:** slower availability burn (>3x over 1d/2h, or >1x over 3d/6h). Budget will run out before month end.
**First checks:** same as the page alert; look for flapping probes, certificate expiry, intermittent pod restarts.
**Escalate:** open a ticket; raise to platform owner if budget under 25%.

## StyxLaunchBurnRatePage

**Means:** desktop launches exceed 10 s too often (>14.4x or >6x burn, more than 5 launches in the window).
**First checks:**
1. Launch duration histogram by `outcome`; failures or slow successes?
2. Image pulls (registry/Harbor mirror reachable?), pending pods, `styx:free_desktop_slots`.
3. Storage provisioning latency for home volumes.
**Escalate:** platform owner; capacity alerts firing together point at [headroom](#styxheadroomcritical).

## StyxLaunchBurnRateTicket

**Means:** slow launch burn (>3x over 1d/2h, or >1x over 3d/6h).
**First checks:** trend by template; large or uncached images, node image-pull times.
**Escalate:** ticket to platform owner; consider pre-pulling images.

## StyxLaunchP50AboveGoal

**Means:** median launch time over 1 day is above the 5 s goal (ceiling is p95 < 10 s).
**First checks:** which templates slowed; recent image size changes; node pressure.
**Escalate:** ticket only.

## StyxStreamRttBurnRatePage

**Means:** too many stream RTT samples above 80 ms (>14.4x or >6x burn). RTT is network round trip, not input-to-photon.
**First checks:**
1. RTT by site or user group; one network or all?
2. TURN/WebRTC path health ([WebRTC and TURN](webrtc-turn.md)); relay vs direct.
3. Node network saturation, Traefik load.
**Escalate:** network owner if the problem is isolated to a site or uplink.

## StyxStreamRttBurnRateTicket

**Means:** slow RTT burn (>3x over 1d/2h, or >1x over 3d/6h).
**First checks:** same as the page alert; look for time-of-day patterns and specific clients.
**Escalate:** ticket to network owner.

## StyxHeadroomLow

**Means:** free desktop slots are fewer than the largest node holds; a node loss cannot be absorbed (N+1).
**First checks:** `styx:free_desktop_slots`, `styx:node_free_desktop_slots` per node; stale or idle desktops to reclaim.
**Escalate:** ticket to add node capacity.

## StyxHeadroomCritical

**Means:** free slots are below 10% of peak (`styx_capacity_peak_desktops`, default 200). New launches will soon fail.
**First checks:** as above; stop idle instances, cordoned nodes, pending pods.
**Escalate:** page platform owner to add capacity now.

## StyxTraefik5xxRatio

**Means:** more than 5% of Traefik requests returned 5xx for 10 min.
**First checks:** `traefik_service_requests_total{code=~"5.."}` by service; backend pod health and logs; upstream workstation gateways.
**Escalate:** platform owner if backend or Traefik is the source.

## StyxBackendDown

**Means:** Prometheus cannot scrape the backend (critical).
**First checks:** `kubectl -n styx get pods,events`; backend logs; database (CNPG) availability; network policies.
**Escalate:** page platform owner. Also see [Kubernetes](kubernetes.md#reliability).

## StyxBackupFailed

**Means:** the last backup job failed.
**First checks:** job logs, storage target reachability and credentials. See [Backup schedules](backup-schedules.md).
**Escalate:** ticket; page if two consecutive runs fail.

## StyxBackupStale

**Means:** no successful backup within the expected interval.
**First checks:** schedule suspended? CronJob last run, storage quota.
**Escalate:** same as `StyxBackupFailed`.

## monitoring_silent (Watchdog)

**Means:** no Watchdog heartbeat reached the portal for 10 min; `monitoring_silent` is true in `/api/ops/alerts` and no other alert can be trusted.
**First checks:** Prometheus and Alertmanager pods in `monitoring`; Alertmanager webhook route to the portal; portal reachable from Alertmanager.
**Escalate:** page platform owner; treat the system as unmonitored until fixed.
