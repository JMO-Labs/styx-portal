# Harbor registry (enterprise)

The enterprise build runs an internal Harbor registry (ADR-0029, Phase 1 part). Its IaC lives
in `deploy/enterprise/harbor/` and is code only. Nothing in CI deploys it. This page covers
bootstrap, secrets, rotation and the planned Phase 2 and Phase 3 changes.

| Item | Value |
|---|---|
| Chart | `goharbor/harbor` 1.19.4 (Harbor 2.15.4), vendored in `charts/` |
| Host | `harbor.example.internal` (placeholder), internal Traefik only, not on the DMZ HAProxy |
| Database | CNPG cluster `harbor-db` (PG 17, 2 instances), `sslmode=verify-full` |
| Blobs | Ceph RGW bucket `harbor-registry` (ObjectBucketClaim) |
| Redis | chart-internal Valkey, 1 replica |
| Auth | `db_auth`: `admin` plus robot accounts only |
| Scanning | Trivy disabled until Phase 3 |

!!! danger "Never create local users"
    **One local Harbor user other than `admin` locks Harbor to database auth forever, so the
    Phase 2 switch to OIDC becomes impossible.** Use robot accounts for automation and wait for
    OIDC for people. `harbor_bootstrap.py` never calls the users API.

## Bootstrap order

1. **Rook-Ceph** (#3): `ceph-block` and `ceph-bucket` storage classes and the RGW object store.
2. **OpenBao and External Secrets** (#4): ClusterSecretStore `openbao`. Fill the paths below.
3. **CNPG operator and barman-cloud plugin** (#24).
4. **Harbor**:

    ```bash
    kubectl apply -k deploy/enterprise/harbor
    kubectl -n harbor wait cluster/harbor-db --for=condition=Ready --timeout=15m
    helm template harbor deploy/enterprise/harbor/charts/harbor-1.19.4.tgz -n harbor \
      -f deploy/enterprise/harbor/values.yaml | kubectl apply -n harbor -f -
    ```

5. **Projects and robot** with `harbor_bootstrap.py` from an admin workstation:

    ```bash
    export HARBOR_URL=https://harbor.example.internal
    export HARBOR_CA_FILE=/path/to/org-ca.crt
    read -rs HARBOR_ADMIN_PASSWORD && export HARBOR_ADMIN_PASSWORD   # from OpenBao kv/harbor/admin
    python3 deploy/enterprise/harbor/harbor_bootstrap.py --dry-run
    python3 deploy/enterprise/harbor/harbor_bootstrap.py --secret-out ./ci-push.secret
    ```

    The script creates the private projects `styx`, `golden` and `platform` and the system robot
    `ci-push` (push and pull on those projects). It prints only the robot name and the secret
    file path. Store the secret in OpenBao at `kv/harbor/robot-ci` (`name`, `secret`), then
    shred the file. Re-running it is safe: it only creates what is missing.

**Seed bundle.** Every image is pinned as `harbor.example.internal/...@sha256`, including
Harbor's own images and the Phase 1 platform images. Harbor cannot serve itself before it
exists. The Phase 1 seed bundle (follow-up issue) imports those images into RKE2 on every node
before step 1 and pushes them into Harbor afterwards. Until it lands, bootstrap needs the
bundle built by hand.

## OpenBao paths

| Path | Keys | Becomes Secret |
|---|---|---|
| `kv/harbor/admin` | `password` | `harbor-admin` (`HARBOR_ADMIN_PASSWORD`) |
| `kv/harbor/secret-key` | `value` (exactly 16 characters) | `harbor-secret-key` (`secretKey`) |
| `kv/harbor/tls` | `tls.crt`, `tls.key`, `ca.crt` (org CA, ADR-0049) | `harbor-tls` (`kubernetes.io/tls`) |
| `kv/harbor/robot-ci` | `name`, `secret` | `harbor-bootstrap-robot` |
| `kv/harbor/db-offsite` | `access_key_id`, `secret_access_key` | `harbor-db-offsite` (barman-cloud) |
| `kv/harbor/core` | `secret` (16 chars) | `harbor-core-secret` (`secret`) |
| `kv/harbor/core-token` | `tls.crt`, `tls.key` (self-signed RSA token signing pair) | `harbor-core-token` |
| `kv/harbor/core-xsrf` | `value` (32 chars) | `harbor-core-xsrf` (`CSRF_KEY`) |
| `kv/harbor/jobservice` | `value` (16 chars) | `harbor-jobservice-secret` (`JOBSERVICE_SECRET`) |
| `kv/harbor/registry-http` | `value` (16 chars) | `harbor-registry-http` (`REGISTRY_HTTP_SECRET`) |
| `kv/harbor/registry-credentials` | `password`, `htpasswd` (`htpasswd -nbB harbor_registry_user <password>`) | `harbor-registry-credentials` |

The six internal secrets above replace values the chart would otherwise generate at random on
every `helm template` (no cluster `lookup`), which would rotate the token key and roll every
Harbor pod on each apply. Generate them once, for example
`openssl genrsa 4096` plus `openssl req -x509 -days 3650 -subj /CN=harbor-token-ca` for the token pair.

CNPG creates `harbor-db-app` and `harbor-db-ca`. Rook creates the OBC Secret
`harbor-registry-bucket` (not `harbor-registry`, which the chart already uses), which ESO maps to `harbor-s3` inside the namespace.

The admin password also belongs in the offline escrow set (D25).

## Rotation

- **Robot `ci-push`:** in the Harbor UI (Administration, Robot Accounts) refresh the secret, or
  delete the robot and re-run `harbor_bootstrap.py --secret-out`. Write the new secret to
  `kv/harbor/robot-ci` and update the GitLab CI variable. ESO refreshes the Secret within 1 h.
- **Admin password:** change it in the Harbor UI first, then write it to `kv/harbor/admin` and
  update the offline escrow copy. Harbor reads `HARBOR_ADMIN_PASSWORD` only on first start,
  but the exporter uses it and a fresh install or restore needs the current value.
- **Robot permissions:** `harbor_bootstrap.py` only creates a missing robot; it does not
  reconcile the permissions of an existing `ci-push`. Fix drift in the UI.
- **Secret key:** do not rotate it. Harbor encrypts stored credentials with it.
- **TLS:** write the renewed cert to `kv/harbor/tls`. After ESO syncs, Traefik picks it up.

## Phase 2: switch to OIDC

Set `auth_mode` to `oidc_auth` in `core.configureUserSettings`, with Keycloak as the
provider (`oidc_endpoint`, `oidc_client_id`, client secret from OpenBao, `oidc_auto_onboard`,
`oidc_admin_group`). The switch only works while no local users exist apart from `admin`.
Robot accounts keep working.

## Phase 3: Trivy (air-gapped)

Set `trivy.enabled: true` and keep it offline: `trivy.skipUpdate: true`,
`trivy.skipJavaDBUpdate: true` and `trivy.offlineScan: true`, or point `trivy.dbRepository`
and `trivy.javaDBRepository` at a `trivy-db` mirrored into Harbor. The Trivy image is already
pinned in `values.yaml`.

## Availability

Portal, core, jobservice and registry run 2 replicas each, with a PodDisruptionBudget of
`maxUnavailable: 1`. CNPG keeps its own PDBs for `harbor-db`. **Valkey is a single replica.**
When it reschedules, push, pull and the UI fail for about 1 minute, and in-flight jobs and UI
sessions drop. Launches are not affected because images are pre-pulled on every worker (D46).

## Network

`networkpolicy.yaml` allows Traefik to reach core and portal, Harbor pods to reach `harbor-db`
on 5432, and the registry to reach the RGW pods (`# PLACEHOLDER(#3)` port). Intra-namespace,
DNS and Prometheus traffic come from the #19 baseline. Internal TLS is off because Cilium
WireGuard (#18) encrypts pod-to-pod traffic (SC-8).
