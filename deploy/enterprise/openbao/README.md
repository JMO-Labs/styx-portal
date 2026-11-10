# OpenBao (enterprise, issue #4)

3-node OpenBao HA cluster on the control plane: Raft on local NVMe (never Ceph, ADR-0061),
auto-unseal with a `seal "static"` key file placed by Ansible, TLS from an offline bootstrap CA,
audit to stdout. External Secrets Operator lives in `../external-secrets/`.
Operating procedures: [docs/enterprise/runbooks/openbao.md](../../../docs/enterprise/runbooks/openbao.md).

Not deployed anywhere yet. ADR-0011 compliance debt (SC-13, CM-6) stays open: no FIPS/STIG
exception references are cited, so this must not go to an accredited environment until they are.

## Pinned versions

| Component | Chart | App | Image (mirror to `harbor.example.internal`) |
|---|---|---|---|
| OpenBao | `openbao/openbao` openbao-0.30.7 | v2.7.2 | `ghcr.io/openbao/openbao:2.7.2@sha256:5046911075e137e154ce49ab051502f4ec7cf367d484ae4a4dce665d9b90561f` |
| External Secrets | `external-secrets/external-secrets` external-secrets 2.14.0 | v2.14.0 | `ghcr.io/external-secrets/external-secrets:v2.14.0@sha256:10608eb53e636e744903d5f3657a4d9c44e28d9d9c181b73e07bc7dd2e6884dc` |
| Snapshot upload | - | rclone 1.76.0 | `ghcr.io/rclone/rclone:1.76.0@sha256:7cbeec24a44f206067597c0368be4de90ae19a64d5113c7d1938bd737a81e466` |

The digests are the multi-arch index digests of the upstream tags (OpenBao and rclone from their
GitHub container package pages, ESO from the release's signed SLSA provenance). Copy with
`skopeo copy --all` (or Harbor replication) so the digest is preserved in Harbor.

The chart archives are vendored in `charts/` (`openbao-0.30.7.tgz`, sha256
`fa4e6f3c1bbe936dc7ba079f1303ea56810af2f8600f046d8d5809860a4f980f`;
`../external-secrets/charts/external-secrets-2.14.0.tgz`, sha256
`0a6d9e91b1ff50adfdbf24b50b582babfa7c5b7df42b21974ca4b3fb88ee5e34`), downloaded from the
upstream GitHub releases. CI renders from these files, so it never needs the chart repositories.

## Files

| File | Purpose |
|---|---|
| `values.yaml` | Helm values: HA Raft x3, control-plane pinning, static seal, TLS, hostPath seal dir (read-only) |
| `namespace.yaml` | `openbao` namespace; PSA `enforce: privileged` exception for the hostPath (CM-6, CM-7) |
| `storageclass.yaml`, `local-pvs.yaml` | `openbao-local` (no-provisioner) and one local PV per control-plane node |
| `networkpolicy.yaml` | CiliumNetworkPolicy for the servers and the snapshot job |
| `snapshot-*.yaml` | Nightly Raft snapshot CronJob, its ServiceAccount, params ConfigMap and S3 ExternalSecret |
| `gen-bootstrap-tls.sh` | Offline bootstrap CA (EC P-384, 10 y) and server cert (1 y) |
| `bao_configure.py` | Idempotent configuration: `kv/`, audit, Kubernetes auth, `policies/*.hcl`, `auth-roles.json`, `extra-mounts.json`; with `BAO_GITLAB_JWT_ISSUER` set, also `auth/jwt` and `jwt-roles.json` |
| `jwt-roles.json` | GitLab CI JWT roles (#10): `gitlab-mirror`, bound to `project_path` and `ref_protected`, policy `gitlab-mirror`, TTL 900 s. `project_path` and `bound_audiences` are placeholders until deployment |
| `ansible/seal-key.yml` | Places the 32-byte seal key and creates the Raft directory on group `masters` |

## Render and validate

```sh
helm template openbao charts/openbao-0.30.7.tgz --skip-tests -n openbao -f values.yaml
kubectl kustomize .
ansible-playbook -i ansible/inventory.example.yml ansible/seal-key.yml --syntax-check
```

The release name must be `openbao` (pod DNS `openbao-N.openbao-internal`, TLS SANs, the
ClusterSecretStore URL). `ansible/inventory.example.yml` is a copy of #2's
`deploy/rke2/inventory/hosts.example.yml` until that PR merges.

## CI

`.gitlab-ci.yml` has two jobs for this tree:

- `openbao-iac` renders both vendored charts with `helm template --skip-tests` and fails unless
  exactly one rendered object mounts `/etc/openbao/seal`. It then runs `kustomize build` on both
  directories, `kubeconform -strict` against Kubernetes 1.36.6, `yamllint`, `shellcheck`,
  `ansible-lint` and `--syntax-check`.
- `openbao-integration` runs `backend/tests/integration/test_openbao_static_seal.py` with
  `OPENBAO_IT=1` against the sha256-pinned `bao` 2.7.2 release binary.

GitHub Actions does not run these jobs yet. The matching `ci.yml` patch is in the body of
PR JMO-Labs/styx-portal#131, and someone with the token `workflow` scope has to apply it. Until
then, `helm template` and the seal-hostPath count have not run in any CI. Run them locally
(see above) before you change `values.yaml`.

## Extending (#20)

Add a mount to `extra-mounts.json` (`[{"path": "rook", "type": "kv-v2"}]`), a policy file to
`policies/`, and a role to `auth-roles.json`, then rerun `bao_configure.py`. No code change.
