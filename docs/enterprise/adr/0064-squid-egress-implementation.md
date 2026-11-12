# ADR-0064: Squid egress implementation

- Status: Accepted
- Date: 2026-11-12
- Decision ID: D63
- Related controls: SC-7, SC-7(5), AC-4, AU-12
- Refines: ADR-0040

## Context

ADR-0040 chose an on-prem Squid proxy with category blocking and a per-group allowlist mode. This ADR records how it is built. Code and manifests exist; nothing is deployed.

## Decision

- **Two Squid ports.** 3128 is category mode (internet minus blocked categories). 3129 is allowlist mode (only listed hosts). Both are defined in `deploy/enterprise/squid/configmap.yaml`.
- **Selection by pod label, enforced by Cilium.** Styx labels each desktop pod `styx.io/egress-mode: category|allowlist`. Cilium policies in `deploy/k8s/components/cilium-baseline/` allow an allowlist desktop only to 3129 and every other desktop only to 3128. The selectors are mutually exclusive, so a desktop cannot switch ports to bypass the allowlist. The proxy env vars are a convenience; Cilium is the control.
- **One shared allowlist.** A single `squid-allowlist` ConfigMap serves every allowlist-mode group. There are no per-group lists.
- **Strictest group wins.** A user in several groups gets `allowlist` if any group has it, otherwise `category` (`backend/app/services/egress_mode.py`). The mode is read when the desktop launches.
- **UT1 categories.** Blocked: `filehosting`, `webmail`, `vpn`, `redirector`, `strong_redirector`, plus a vendored `paste` list. A daily CronJob (`squid-categories-update`) refreshes them from UT1 into an RWX PVC. If any download fails, the old lists stay.
- **Hostname-only logs.** No SSL-bump; HTTPS is tunnelled. The Squid access log is one JSON line per request with `%>rd` (host only; no path or query). Fluent Bit ships it to the `logs-squid.access-*` data stream in Elastic and drops anything that is not a bare hostname.

## Alternatives considered

- Per-group allowlists: more ConfigMaps and policies for little gain; rejected for now.
- Mode chosen by the proxy from user identity: needs proxy auth; the label plus Cilium needs none.
- Most permissive group wins: weakens the allowlist for users who are also in a default group.

## Consequences

Positive:

- Bypassing the proxy or the allowlist is blocked at the network layer, not by client settings.
- Hostname decisions are searchable in Elastic.

Negative:

- A mode change reaches a desktop only on its next launch.
- Uncategorised hosts stay reachable in category mode (R01, ADR-0040).
- Not deployed: no evidence from a live cluster yet.
