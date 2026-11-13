# Load-test gate (D47): 200-session soak

Owner runbook for the evidence in ADR-0047. Design: ADR-0077. Harness: `e2e/stream-ab/` (`soak.py`, `fleet.py`, `session_probe.py`, `gate.py`). Plumbing smoke (not capacity evidence): `scripts/kind/30-loadtest-smoke.sh`.

## Pass criteria

| Metric | Threshold |
|---|---|
| Launch p95 | < 10 s, and no failed launch |
| Stream RTT p95 (client-side) | < 80 ms |
| Drops | 0 over the whole run |

Run length: 240 minutes with 200 sessions.

## Capacity prerequisites

Check before starting; a shortfall fails the gate for the wrong reason.

- **Cluster:** the ADR-0006 layout, 8 workers (128 cores / 512 GB each), all Ready, no cordoned node. Rook-Ceph healthy (`HEALTH_OK`).
- **Per session (CPU tier, ADR-0031):** ~3 cores and 4 GB. 200 sessions = ~600 cores and ~800 GB RAM, plus ~100 cores of platform services and ~4 cores per node for Ceph OSDs (ADR-0009, 0055). No GPU is needed (CPU tier).
- **Quotas:** the test user and its group allow 200 concurrent desktops (per-group session and CPU/memory caps raised; namespace ResourceQuota and LimitRange fit 200 x 3 cores / 4 GB). Home quota (10 GB per user, ADR-0034) covers 200 homes on CephFS.
- **Images:** the golden image digest is pre-pulled on all nodes (ADR-0076); confirm the pre-pull reports ready, or launch p95 measures image pulls.
- **Load generator:** a separate host on the user network path (not on a cluster node). Needs Python 3.12 with `requests`, node with Playwright and Chromium for `latency.mjs`, and capacity for 200 parallel browser probes (plan at least 1 core and 1 GB each, ~200 cores / 200 GB, or split across hosts and run per-host only for tuning, not for the gate).
- **Account:** a portal user allowed to create instances. Credentials go in `STYX_USER` / `STYX_PASS`; never put them on the command line or in files in the repo.
- **Window:** 4.5 hours with no deploys, node drains or image rollouts.

## Run

```bash
cd e2e/stream-ab
export STYX_PORTAL=https://<portal-host>   # or pass --portal
export STYX_USER=<load-test user> STYX_PASS=<password>
python3 soak.py --sessions 200 --minutes 240 --probe stream
```

Defaults: `--template selkies-desktop`, launch timeout 300 s per session. Sessions are named `fleet-0` to `fleet-199` and served at `https://fleet-N.<portal-host>/`. Exit code 0 = pass, 1 = fail. Run it under `tmux` or `nohup`; Ctrl-C or SIGTERM tears the sessions down.

During the run watch the Grafana SLO and capacity dashboards (ADR-0044): worker CPU, Ceph latency, launch p95 alert (`StyxLaunchP95High`).

## Read the report

Written to `e2e/stream-ab/results/gate-<YYYYmmdd-HHMMSS>.json` and `.md`. The terminal prints `gate: pass|fail (N sessions)`.

- `verdict`: `pass` only if every metric passes and there was at least one session.
- `n_sessions`: must be 200. Fewer means launches failed (they count as failures in `failed_launches`).
- `metrics.launch_p95_s`: value vs 10 s; `failed_launches` must be 0.
- `metrics.rtt_p95_ms`: value vs 80 ms, pooled over all sessions.
- `metrics.drops`: total, must be 0.

A missing value (`-`) is a fail: no launches or no samples. On fail, look at which metric failed, then at node CPU and Ceph at that time. Do not re-run with relaxed thresholds. If CPU is the limit, the CPU caps (ADR-0031) are not final: adjust them and repeat. Attach the `.json` and `.md` to the rollout decision (ADR-0047).

## Cleanup

`soak.py` deletes its sessions on exit, also on failure. Verify:

```bash
kubectl get pods -A | grep fleet-    # expect nothing
```

If any remain (killed with SIGKILL, lost portal connection), delete them in the portal admin console or via the API (`DELETE /api/instances/<id>`), then confirm the pods and per-session volumes are gone and the quota is free. Remove the load-test user's homes if they were created. Keep the `results/` files; they are the evidence.
