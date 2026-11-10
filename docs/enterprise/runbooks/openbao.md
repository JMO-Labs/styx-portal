# OpenBao and External Secrets runbook

Install, initialise and operate the OpenBao cluster and External Secrets Operator (ESO) from
`deploy/enterprise/openbao/` and `deploy/enterprise/external-secrets/` (issue #4, ADR-0042).
Design inputs: C1 (static seal key file, escrowed) and A1 (offsite snapshot prefix) from
[full-site-restore.md](full-site-restore.md).

!!! warning "Compliance debt"
    ADR-0011 is still Proposed. The FIPS/STIG exception references (issuer, date, scope,
    eMASS ID) are not cited, so SC-13 and CM-6 stay open. Do not deploy to an accredited
    environment until they are.

## Install order

Each step needs the previous one. Commands assume the repository root.

1. **Seal key escrow.** On an offline machine: `openssl rand -out <key-id>.key 32`. Choose
   `<key-id>` as `YYYYMMDD-n`. Put the key and its id in **both** escrow sets (C1) before
   anything else. A key that is placed but not escrowed is a future total loss.
2. **Ansible.** Place the key and create the Raft directory on every control-plane node:
   `ansible-playbook -i <inventory> deploy/enterprise/openbao/ansible/seal-key.yml
   -e openbao_seal_key_src=<path>/<key-id>.key -e openbao_seal_key_id=<key-id>`.
   It fails early unless the file is exactly 32 bytes. Set the same `<key-id>` in
   `values.yaml` (`current_key_id`, `current_key`).
3. **TLS.** Offline: `deploy/enterprise/openbao/gen-bootstrap-tls.sh <outdir>` (outside any
   git checkout). Escrow `ca.key` offline.
4. **Secrets.** Create the namespaces (`kubectl apply -f deploy/enterprise/openbao/namespace.yaml
   -f deploy/enterprise/external-secrets/namespace.yaml`), then run the two
   `kubectl create secret` commands the TLS script printed (`openbao/openbao-tls`,
   `external-secrets/openbao-ca`) and delete the local `tls.key`.
5. **Local PVs.** `kubectl apply -f deploy/enterprise/openbao/storageclass.yaml
   -f deploy/enterprise/openbao/local-pvs.yaml`. Check the three
   `openbao-raft-rke2-server-0N` PVs are `Available` and their hostnames match the real control-plane node names.
6. **Helm.** `helm install openbao deploy/enterprise/openbao/charts/openbao-0.30.7.tgz -n openbao
   -f deploy/enterprise/openbao/values.yaml`. The pods start sealed and uninitialised.
   Warning: never run `helm test` on this release: the chart's test pod copies the seal-key hostPath
   without control-plane pinning (render with `helm template --skip-tests`).
7. **Init** (below).
8. **Configure.** With the root token in `BAO_TOKEN`, a port-forward to `openbao-active`, and
   `BAO_CACERT` pointing at the bootstrap `ca.crt`: run `bao_configure.py --dry-run`, review,
   then run it without `--dry-run`. It is idempotent; rerun it after any change to
   `policies/`, `auth-roles.json` or `extra-mounts.json`. Store the snapshot bucket
   credentials from offline media, so they stay out of shell history:
   `bao kv put kv/openbao/snapshot-s3 @creds.json` (keys `AWS_ACCESS_KEY_ID`,
   `AWS_SECRET_ACCESS_KEY`).
   Then revoke the root token: `bao token revoke -self`.
9. **ESO.** `helm install external-secrets
   deploy/enterprise/external-secrets/charts/external-secrets-2.14.0.tgz -n external-secrets
   -f deploy/enterprise/external-secrets/values.yaml`, then `kubectl apply -k` both directories
   (network policies, snapshot job, ClusterSecretStore).
   `kubectl get clustersecretstore openbao` must show Ready.

## Init

```sh
kubectl -n openbao exec -it openbao-0 -- bao operator init -recovery-shares=3 -recovery-threshold=2
```

With auto-unseal, init returns **recovery keys**, not unseal keys. They can authorise
`bao operator generate-root` and similar operations; they can never unseal. Give one share to
each of the 3 holders (ADR-0042) and never store two shares together. The 2-of-3 threshold is a
parameter: the owner confirms it with the ADR-0042 escrow custody follow-up.

Audit logging needs no step: `values.yaml` declares `audit "file" "stdout"` in the server
config, because OpenBao 2.7 refuses audit devices created over the API. The log collector
(#11) ships it from the pod stdout. `bao_configure.py` stops if the device is missing.

The other pods join through `retry_join` and unseal themselves. Check:
`bao status` shows `Sealed false`, `Seal Type static`, and `bao operator raft list-peers`
lists 3 voters. Use the root token only for step 8, then revoke it.

## Static seal key rotation

The static seal reads its keys only at startup, so rotation is a rolling restart.

1. Generate the new key and id offline (`openssl rand -out <new-id>.key 32`) and escrow it in
   **both** escrow sets first.
2. Run `seal-key.yml` with the new key and id. The old key file stays on the nodes.
3. In `values.yaml` set `current_key_id`/`current_key` to the new key and uncomment
   `previous_key_id`/`previous_key` with the old one. `helm upgrade`.
4. The StatefulSet uses `OnDelete`: delete the standby pods one at a time, then the active
   pod, waiting for each to report `Sealed false` before the next.
5. Keep the old key on the nodes and in escrow until the **last raft snapshot wrapped by it
   has aged out of the A1 offsite retention**. Snapshots taken before rotation can only be
   restored with the old key and id. Only then remove `previous_*` and the old key file.

## Bootstrap CA and server certificate renewal

The server certificate lasts 1 year, the CA 10 years. Renew the server certificate at least
30 days before expiry:

1. Offline, issue a new `tls.crt`/`tls.key` from the escrowed CA with the same SANs (the
   script refuses a directory that already holds keys; use a fresh one and copy `ca.crt`/`ca.key`
   in, or rerun it for a full CA rollover).
2. Replace Secret `openbao/openbao-tls` and restart the pods one at a time as above.
3. For a CA rollover, first put **both** CAs in `ca.crt` of `openbao-tls` and
   `external-secrets/openbao-ca`, restart, then switch the server certificate, then drop the
   old CA. ESO and Rook pin this CA.

## Onboarding a namespace to ESO

The `ClusterSecretStore` `openbao` serves only namespaces labelled
`styx.io/openbao-secrets=true`. Only platform admins may set the label:

```sh
kubectl label namespace <ns> styx.io/openbao-secrets=true
```

Then create `ExternalSecret`s that reference `ClusterSecretStore/openbao` with keys under
`kv/` (for example `backup/offsite/kopia` for #13).

**Accepted risk:** one store and one read role (`eso-read`) means a labelled namespace can
read all of `kv/`. Infra secrets that need isolation (Rook KEKs, #20) go in separate mounts
that `eso-read` cannot read. Per-namespace `SecretStore`s with path-scoped roles are a later
hardening step.

## Snapshot restore

The CronJob `openbao-raft-snapshot` saves a Raft snapshot every night at 02:00 UTC to
`s3://<BUCKET>/openbao/` (ConfigMap `openbao-snapshot-params`, A1 prefix). To restore, follow
[full-site-restore.md](full-site-restore.md) step 3:

1. Place the static seal key that was current when the snapshot was taken
   (`/etc/openbao/seal/<key-id>.key`, `seal-key.yml`) and deploy with that key id.
2. Init the new cluster, then `bao operator raft snapshot restore -force <file>` with its
   root token.
3. Restart the pods; they auto-unseal with the static key. Tokens and data are now those of
   the snapshot.

A snapshot restored with the wrong key stays sealed. The integration test
`backend/tests/integration/test_openbao_static_seal.py` covers restart, wrong key, rotation
and restore.

## Why OpenBao must not use Ceph

Ceph OSDs are encrypted with dm-crypt and fetch their keys from OpenBao at start (ADR-0061).
If OpenBao's Raft data were on Ceph, a cold start would deadlock: OSDs wait for OpenBao,
OpenBao waits for its volume on Ceph. So Raft lives on `openbao-local` PVs on the control-plane
NVMe. `backend/tests/test_enterprise_openbao.py::test_raft_not_on_ceph` guards this.

## Compliance debt

- ADR-0011 is still **Proposed**; the R05 gate was waived by the owner for code only
  (Slack #wq-exec 1794257851.219479). SC-13 and CM-6 stay open until the exception
  references are cited.
- The `openbao` namespace runs with PSA `enforce: privileged` for the read-only seal hostPath
  (CM-6, CM-7 exception in the control matrix).
- The recovery threshold (2-of-3) awaits owner confirmation with escrow custody (ADR-0042).
