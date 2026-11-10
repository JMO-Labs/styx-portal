# Harbor registry (enterprise, Phase 1)

IaC for the internal Harbor registry (issue #5, ADR-0029 Phase 1 part). It is code
only: nothing here is deployed by CI. The runbook is
[docs/operate/harbor-enterprise.md](../../../docs/operate/harbor-enterprise.md).

| Item | Value |
|---|---|
| Chart | `goharbor/harbor` **1.19.4** (appVersion **2.15.4**) |
| Registry host | `harbor.example.internal` (placeholder, internal Traefik only) |
| Namespace | `harbor` |
| Database | CNPG `harbor-db`, PG 17, 2 instances, barman-cloud plugin backups |
| Blobs | Ceph RGW S3 via ObjectBucketClaim `harbor-registry` |
| Redis | chart-internal Valkey, 1 replica |
| Auth | `db_auth`, `admin` and robots only (Phase 2: `oidc_auth`) |
| Trivy | disabled (Phase 3) |

## Files

| File | Purpose |
|---|---|
| `values.yaml` | Chart overrides: external DB with `verify-full`, S3 with `disableredirect`, 2 replicas, digest-pinned images, existing Secrets only |
| `namespace.yaml` | Namespace, PSA `restricted`, OpenBao secrets label |
| `harbor-db.yaml` | CNPG `Cluster`, barman `ObjectStore`, daily `ScheduledBackup` |
| `objectbucketclaim.yaml` | RGW bucket `harbor-registry` (`ceph-bucket`, #3) |
| `s3-credentials.yaml` | ESO kubernetes-provider store that maps the OBC keys to `harbor-s3` |
| `external-secrets.yaml` | `harbor-admin`, `harbor-secret-key`, `harbor-tls`, `harbor-bootstrap-robot`, `harbor-db-offsite` from `openbao` |
| `networkpolicy.yaml` | Traefik to core/portal, Harbor to `harbor-db`, registry to RGW |
| `pdb.yaml` | `maxUnavailable: 1` for portal, core, jobservice, registry (CNPG owns the `harbor-db` PDBs) |
| `harbor_bootstrap.py` | Idempotent projects (`styx`, `golden`, `platform`) and system robot `ci-push` |
| `charts/harbor-1.19.4.tgz` | Vendored chart |

## Render (what CI runs)

```bash
helm template harbor deploy/enterprise/harbor/charts/harbor-1.19.4.tgz -n harbor \
  -f deploy/enterprise/harbor/values.yaml > harbor-chart.yaml
kubectl kustomize deploy/enterprise/harbor > harbor-extra.yaml   # CI: kustomize 5.8.3 build
kubeconform -strict -ignore-missing-schemas -kubernetes-version 1.36.6 \
  harbor-chart.yaml harbor-extra.yaml
```

The GitLab job is `harbor-iac` in `.gitlab-ci.yml`. `backend/tests/test_enterprise_harbor.py`
runs the same render when `helm` is installed.

**Vendored chart.** `https://helm.goharbor.io` was not reachable when this was built (and runners may be offline),
so the chart is vendored. `charts/harbor-1.19.4.tgz` is the
[v1.19.4 tag](https://github.com/goharbor/harbor-helm/releases/tag/v1.19.4) of
`goharbor/harbor-helm` packaged as `harbor/` (without `docs/` and `test/`).
Its `values.yaml` holds the upstream default secrets; `values.yaml` here replaces the
admin password and secret key with existing Secrets (see Known limits).

## Images

Every image is `harbor.example.internal/<upstream path>:<tag>@sha256:<digest>` with the
upstream digest (`docker.io/goharbor/*:v2.15.4`, `ghcr.io/cloudnative-pg/postgresql:17.11`).
Harbor cannot serve its own images before it exists: the Phase 1 seed bundle
(follow-up issue) imports them into RKE2 first. To bump, take the digests from the
new chart's upstream images and keep the prefix.

## Placeholders

- `# PLACEHOLDER(#3)`: RGW endpoint and port, `ceph-bucket` and `ceph-block` classes.
- `# PLACEHOLDER(#24)`: offsite bucket path and endpoint for barman-cloud.
- `syslog.example.internal:514`: audit log forwarding target (#11).

## Known limits

- The chart still renders its default internal registry credentials
  (`registry.credentials`), used only between core and registry inside the namespace.
  Moving them to an existing Secret is a follow-up.
- Barman offsite egress from `harbor-db` pods follows the #24 egress pattern and is not
  in `networkpolicy.yaml`.
