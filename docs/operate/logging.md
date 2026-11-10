# Log and audit shipping (Elastic SIEM)

The enterprise profile ships Styx audit events, container logs and the RKE2
kube-apiserver audit log to the org Elastic SIEM (ADR-0044, AU-2/3/5/11/12). The
shipper is Fluent Bit, installed by the RKE2 helm-controller from charts and images
mirrored in Harbor. Everything lives in `deploy/logging/`. It is IaC only: **not
deployed** and not for accredited environments until SC-13 and CM-6 are closed.

| Piece | What it does |
|---|---|
| `backend/app/services/audit_ecs.py` | Every `audit()` call also writes one ECS JSON line to stdout (logger `styx.audit`). Hooks `egress_event()` (phase 3, Squid) and `dlp_event()` (phase 4, metadata only) |
| `helmchart.yaml` `fluent-bit` | DaemonSet on every node: container logs to `logs-kubernetes.container_logs-default`; Styx audit lines from `styx/backend` only to `logs-styx.audit-default` (`_id` = `event.id`) |
| `helmchart.yaml` `fluent-bit-audit` | DaemonSet on control-plane nodes only: tails `/var/lib/rancher/rke2/server/logs/audit.log` (read-only hostPath) to `logs-kubernetes.audit_logs-default` |
| `lua-configmap.yaml` | Lua: Styx audit routing and the k8s audit to ECS map (raw event kept in `kubernetes.audit`) |
| `networkpolicy.yaml` | Egress only to DNS, the Elastic FQDN on 443/9200 and the API server; ingress only for the Prometheus scrape |
| `prometheusrule.yaml` | AU-5 alerts: `FluentBitOutputFailing`, `FluentBitRetriesHigh`, `FluentBitDown` |
| `components/external-secret/` | Opt-in: `ExternalSecret` `elastic-shipper` from OpenBao `kv/styx/logging/elastic` |
| `rke2/audit-policy.yaml` | kube-apiserver audit policy (RKE2's default policy logs nothing) |
| `elastic/` | ILM `styx-logs`, component templates `styx@settings` and `styx-ecs@mappings`, one index template per data stream, role `styx-shipper`, `bootstrap.py` |

## Install

1. **Audit policy (#2).** Copy `rke2/audit-policy.yaml` to
   `/etc/rancher/rke2/audit-policy.yaml` on every server node and set
   `audit-policy-file: /etc/rancher/rke2/audit-policy.yaml` in the RKE2 config.
   Keep RKE2's rotation flags (`audit-log-maxage=30`, `maxbackup=10`, `maxsize=100`).
2. **Mirror into Harbor.** Chart `fluent/fluent-bit` 0.58.3 (OCI) and image
   `fluent/fluent-bit:5.1.3` into the `fluent` project. Fluent Bit must not depend on
   Harbor audit forwarding (see Open items).
3. **Elastic bootstrap** (below), then mint the shipper key.
4. **Parameters.** Replace `siem.example.internal` in `helmchart.yaml` (`ELASTIC_HOST`)
   and `networkpolicy.yaml`. Replace `elastic-ca.example.crt` with the org CA bundle
   (PEM). Fluent Bit refuses to connect until it is real (`tls.verify On`).
5. **Secret.** Until OpenBao/ESO (#4) is live: `cp secrets.example.env secrets.env`, set
   `ELASTIC_API_KEY`, and point `secretGenerator` at `secrets.env` locally (never commit
   it). With #4 live, put the key in OpenBao (`bao kv put kv/styx/logging/elastic
   api_key=-`) and add `components: [components/external-secret]` to the kustomization.
   The component deletes the placeholder Secret and labels the namespace for the
   `openbao` ClusterSecretStore.
6. **Apply:** `kubectl apply -k deploy/logging`. Check:
   `kubectl -n logging get pods`, `kubectl -n kube-system get helmchart fluent-bit fluent-bit-audit`.

## Elastic bootstrap

`elastic/bootstrap.py` (stdlib) PUTs the ILM policy, component templates, index
templates and the `styx-shipper` role. Every request is a PUT, so re-running it is
safe. It uses a separate **setup** key that has `manage_ilm`, `manage_index_templates`
and `manage_security`, never the shipper key.

```bash
cd deploy/logging/elastic
./bootstrap.py --dry-run                         # list requests, no network
export ELASTIC_URL=https://siem.example.internal:9200 ELASTIC_CA_FILE=/path/org-ca.pem
read -rs ELASTIC_SETUP_API_KEY && export ELASTIC_SETUP_API_KEY
RETENTION_DELETE_DAYS=455 ./bootstrap.py
```

`RETENTION_DELETE_DAYS` must be at least 365. ILM phase ages count from rollover, so a
document can live up to 30 days (`max_age`) longer than the delete age. That
over-retains and never under-retains. The index templates have priority 250, above the
built-in `logs-*-*` (100) and the Elastic Kubernetes integration (200). If the SIEM
team already runs that integration, agree with them who owns
`logs-kubernetes.*`. Mappings are `dynamic: false`: unmapped fields stay in `_source`
and can be queried with runtime fields, so arbitrary app JSON can't blow up the mapping.

## Shipper key and rotation

The shipper key only appends (`create_doc`, `auto_configure` on `logs-styx.*-*` and
`logs-kubernetes.*-*`). Mint it with the role descriptor from `elastic/roles/styx-shipper.json`:

```
POST /_security/api_key
{"name": "styx-shipper-<date>", "expiration": "365d",
 "role_descriptors": {"styx-shipper": <contents of roles/styx-shipper.json>}}
```

Store the `encoded` value in OpenBao (or `secrets.env`), never in Git or a ticket.
Rotation: mint the new key, write it to OpenBao, wait for ESO to refresh (`refreshInterval: 1h`,
or annotate the ExternalSecret with `force-sync`), restart both DaemonSets
(`kubectl -n logging rollout restart ds`), confirm documents still arrive, then
`DELETE /_security/api_key` the old id. The setup key gets the same treatment, held
by the SIEM team.

## Outage and buffering

Every output has `retry_limit false` and filesystem buffering on the node
(`/var/lib/fluent-bit/main` and `/var/lib/fluent-bit/audit`). If Elastic is down, chunks
pile up on disk and are sent when it returns. Writes use `create`. Styx audit uses
`_id = event.id` and the other streams use `generate_id`, so a replay after a timeout
gets a 409 instead of a duplicate. Records are lost only when an output's
`storage.total_limit_size` is full (styx audit 2G, container logs 8G, apiserver audit
8G per node). At that point Fluent Bit drops the oldest chunks, and
`FluentBitOutputFailing` fires (dropped records, failed retries or errors for 15 min).
`FluentBitRetriesHigh` is the early warning, and `FluentBitDown` means no shipper metrics
at all. Styx audit rows also stay in the `audit_log` table, so a gap in Elastic can be
backfilled from the database.

Known behaviour:

- The JSON line is written when the event is added to the session, before commit. A
  rolled-back transaction can leave a line in Elastic with no DB row (over-logs, never
  under-logs).
- Apiserver audit lines longer than 4 MB (`buffer_max_size`) are skipped. The policy keeps
  `RequestResponse` to RBAC writes and `pods/exec|attach|portforward`, which keeps
  events small.
- Only the `styx/backend` container can feed `logs-styx.audit`. An ECS-looking line
  from any other pod stays in container logs.
- The `logging` namespace's own logs are not shipped (avoids feedback loops on errors).

## Log volume estimate

Order of magnitude, to be measured in Pilot 25 (ADR-0044 negative consequence).

| Source | Assumption | /day raw |
|---|---|---|
| Styx audit | 500 users × ~40 events × ~0.6 KB | ~12 MB |
| k8s apiserver audit (Metadata, noise dropped) | 11 nodes, ~200 desktop pods, ~1 KB/event | 1–4 GB |
| Container logs | backend, Keycloak, Traefik, Selkies pods (excludes applied) | 1–5 GB |
| Squid hostnames (phase 3) | 200 concurrent × ~5k req × ~0.4 KB | ~0.4 GB |
| DLP metadata (phase 4) | 200 × ~200 events × 0.3 KB | ~12 MB |
| **Total** | | **~3–10 GB/day** |

90 days hot at roughly 1× on disk after compression, plus 1 replica: **~0.5–1.8 TB**.
Cold for the rest of the retention, at 0 replicas or snapshot-backed: **~1–3.5 TB**. The
cost drivers are container logs and k8s audit. The levers are the `fluentbit.io/exclude`
pod annotation and the audit policy.

## Open items (confirm with the owner before any deployment)

1. **SIEM ownership and privileges.** Can Styx install templates, ILM and a role on the
   org Elastic, or does the SIEM team apply `deploy/logging/elastic/*.json`? Default:
   the SIEM team supplies a setup key and runs `bootstrap.py`.
2. **AU-11 reading.** Is "90 d hot / 1 y archive" a 365-day total or 90 + 365 = 455
   days? The default is 455 (`RETENTION_DELETE_DAYS`).
3. **Licence tier.** Enterprise allows cold as `searchable_snapshot` on Ceph RGW
   (replace `readonly` in the cold phase with
   `{"searchable_snapshot": {"snapshot_repository": "ceph-rgw"}}`). Basic and Platinum
   keep the plain cold phase plus SLM snapshots for archive.
4. **Elastic version.** 8.x+ assumed (`suppress_type_name`, ECS 8.17 field set).
5. **RKE2 (#2).** Final control-plane paths and the `audit-policy-file` wiring.

Harbor audit events are not shipped yet. Harbor 2.15.4 crashes if
`audit_log_forward_endpoint` is unreachable (see the Harbor runbook). They stay in the
Harbor database until a syslog input or an API pull is added.
