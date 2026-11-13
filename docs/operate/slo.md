# SLO alerts

Rules: `deploy/k8s/slo-rules.yaml`. Tests: `scripts/slo_rules_test.sh`.

## StyxLaunchP95High

- **Fires when:** `styx:launch_duration_seconds:p95_5m >= 10` for 15 minutes while `styx:slo_in_scope == 1` (business hours, no maintenance). Severity: warning.
- **Meaning:** the 95th percentile of successful launches (5m window) is at or above 10 s.
- **Check:** the launch duration panel, host load and image pulls, then Docker/Kubernetes scheduling latency.
