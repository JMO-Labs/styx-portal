# Runbook: full-site restore (RTO 8 h)

Use this runbook when the whole site is lost: cluster, Ceph disks, the on-site safe, or all of
these. It rebuilds the platform from IaC on replacement hardware and restores **data** from the
offsite bucket. It does not restore cluster state from etcd (see
[Control-plane-only loss](#control-plane-only-loss)).

Every timing below is an estimate, unproven until #15 (phase 1 restore test). Placeholders marked
`TBD (owner input)` are open owner inputs; fill them in place without changing the structure.

## Scope and decisions

Owner decisions on #14 (2026-11-10), applied throughout:

- **A1** (offsite scope): one object-locked offsite bucket with separate prefixes for CNPG barman-cloud, Velero BSL, OpenBao raft snapshots, the RGW cold-archive mirror and Kopia homes (#13).
- **B1** (escrow): two sealed escrow sets (on-site safe and a second location), each under two-person custody, with quarterly seal checks.
- **C1** (OpenBao seal): `seal "static"` key file, escrowed in both sets; a TPM seal cannot be restored on new hardware.
- **D1** (RTO clock): the 8 h starts when replacement hardware is ready; see [RTO clock](#rto-clock).

Related: ADR-0037 (backup and DR, RPO 24 h, RTO 8 h), ADR-0042 (OpenBao and External Secrets),
ADR-0025 (break-glass), ADR-0026 (admin roles), ADR-0033 (Rook-Ceph), ADR-0036 (CNPG),
ADR-0061 (OSD dm-crypt). Offsite export: #13. Restore test harness and evidence schema: #15.
Risk acceptance: R03 (no second site).

## RTO clock

Decision D1:

- **T0** is the moment replacement hardware is ready: racked, powered and reachable on the
  management network. Hardware procurement and delivery are outside the clock. Record their
  duration separately under R03.
- **Recovered (T_end)** means all three hold: CAC login works, desktop launch works, and the
  homes of priority users (admins, help desk) are restored.
- The remaining homes restore by priority after T_end. Their RPO stays 24 h.
- RTO = T_end − T0. Target: 8 h or less.

## Roles

Name a primary and an alternate for each role before the first restore test (#15).

| Role | Primary | Alternate | Duties |
|------|---------|-----------|--------|
| Incident commander | TBD (owner input) | TBD (owner input) | Declares disaster, starts T0, decides go/no-go per step, declares T_end, signs off |
| Platform admin (executor) | TBD (owner input) | TBD (owner input) | Runs steps 2-8 and 10, records every command in the step log |
| Escrow custodian (2-person) | TBD (owner input) | TBD (owner input) | Retrieve the offsite escrow envelope together, log seal numbers broken and resealed |
| Shamir recovery key holder | TBD (owner input) | TBD (owner input) | Only if a root token is needed in step 3 (recovery keys cannot unseal) |
| Help desk (validation and comms) | TBD (owner input) | TBD (owner input) | Runs the smoke test (step 9), user notices, home-restore priority list |
| ISSO (evidence witness and sign-off) | TBD (owner input) | TBD (owner input) | Witnesses steps, keeps the evidence log, signs the report |

## Before you start

The offsite escrow envelope (B1) must hold:

- Kopia password for the #13 home repository, plus endpoint, region, bucket and prefix
- Offsite bucket credentials (read access for all A1 prefixes)
- OpenBao static seal key (32-byte key file, C1) and its original `current_key_id`; the restored
  raft data is wrapped under that id, so a new id cannot decrypt it
- OpenBao raft snapshot location (bucket prefix and naming)
- RKE2 token (server token; only needed for [Control-plane-only loss](#control-plane-only-loss))
- Velero repo password (`velero-repo-credentials`)
- Break-glass set (two local Keycloak admins, ADR-0025)

Escrow custody:

- Two escrow sets (B1): set 1 in the on-site safe, set 2 at a second location.
- Second escrow location: TBD (owner input)
- Each set is under two-person custody. Seal checks are quarterly and logged.
- For a full-site loss assume set 1 is gone; use set 2.

Inputs and prerequisites:

- Offsite WAN bandwidth (sustained, to the bucket): TBD (owner input). It sets the step 8 window.
- IaC repository and CI on federal GitLab reachable (ADR-0048).
- Replacement hardware per ADR-0006 racked, powered and reachable (this is T0).
- Evidence log opened from the template in [Evidence](#evidence).

## Rebuild order

Fresh rebuild from IaC plus data restore. Step 8 (homes) runs in the background from step 4.

| # | Step | Depends on | Owner role | Estimate |
|---|------|------------|------------|----------|
| 0 | Declare disaster, name incident commander, start T0, open evidence log | — | Platform admin + ISSO | 0:15, unproven until #15 |
| 1 | Retrieve offsite escrow envelope | escrow custodians (2-person) | Escrow custodian | 0:30 (parallel with 2), unproven until #15 |
| 2 | Hardware, network, DMZ HAProxy pair; RKE2 + Cilium + default-deny from IaC | hardware | Platform admin | 1:00, unproven until #15 |
| 3 | OpenBao: static seal, raft snapshot restore, auto-unseal, ESO Ready | 1, 2 | Platform admin + Shamir holder if root token needed | 0:45, unproven until #15 |
| 4 | Rook-Ceph on fresh dm-crypt OSDs, HEALTH_OK, pools | 3 | Platform admin | 1:00, unproven until #15 |
| 5 | Images: Harbor re-populated by CI, cosign key from OpenBao | 3, 4 | Platform admin | 1:00 (parallel with 6-7), unproven until #15 |
| 6 | CNPG: Styx and Keycloak via `bootstrap.recovery` from offsite barman-cloud | 3, 4 | Platform admin | 0:45, unproven until #15 |
| 7 | Velero: offsite BSL, restore app namespaces | 4, 5, 6 | Platform admin | 0:45, unproven until #15 |
| 8 | Homes and profiles: Kopia restore by priority | 1, 4 | Platform admin | data/WAN bound, unproven until #15 |
| 9 | Smoke test | 6, 7 | Help desk + ISSO | 0:45, unproven until #15 |
| 10 | DNS/DMZ cutover, declare T_end, notify users, record RTO/RPO | 9 | Incident commander | 0:15, unproven until #15 |

Critical path without homes: 0 → 2 → 3 → 4 → 5 → 7 → 9 → 10, about 6:15 to 6:45 including
handovers, which leaves about 1.5 h of slack. This holds only if hardware is ready at T0 and the
images build in time. Priority homes (step 8) must finish inside that slack.

## Steps

Log every action in the step log (`id`, `start`, `end`, `actor`, `command`, `result`, UTC).
Secrets from the envelope go into files or prompts, never onto the command line or into the log.

### Step 0: Declare disaster and start the clock

Depends on: —
Owner role: Platform admin + ISSO (incident commander named here)
Estimate: 0:15, unproven until #15
Evidence: step log entry with T0 (UTC), declaration message, named role holders

1. Confirm a full-site loss (not control-plane-only; if the site is intact use [Control-plane-only loss](#control-plane-only-loss)).
2. Name the incident commander and the people filling each [role](#roles).
3. Confirm the replacement hardware is ready and record T0 in UTC (D1).
4. Open the evidence log at `docs/enterprise/evidence/dr/<date>/` from the [template](#evidence).
5. Send the first status notice to users and stakeholders (help desk).

Done when: T0 is recorded, roles are filled and the evidence log is open.

### Step 1: Retrieve the offsite escrow envelope

Depends on: escrow custodians (2-person)
Owner role: Escrow custodian (2-person)
Estimate: 0:30 (parallel with step 2), unproven until #15
Evidence: seal numbers broken, both custodian names, time of handover

1. Both custodians go to the second escrow location and open escrow set 2 together.
2. Record the seal numbers broken, in the presence of both custodians.
3. Check the envelope against the list in [Before you start](#before-you-start).
4. Hand the contents to the platform admin; keep custody of the paper until reseal.

Done when: every envelope item is present and handed over, and seal numbers are logged.

### Step 2: Hardware, network and RKE2 from IaC

Depends on: hardware
Owner role: Platform admin
Estimate: 1:00, unproven until #15
Evidence: IaC commit SHA applied, `kubectl get nodes` output, Cilium status

1. Bring up the network and the DMZ HAProxy pair (#7, ADR-0050).
2. Install RKE2 with Cilium on the control plane and workers from IaC (#2, ADR-0007), with a new token.
3. Apply the Cilium default-deny policies (#18, #19).
4. Check `kubectl get nodes` (all Ready) and `cilium status` (OK).

Done when: all nodes are Ready and default-deny is active.

### Step 3: OpenBao static seal and raft snapshot restore

Depends on: 1, 2
Owner role: Platform admin + Shamir recovery key holder (only if a root token is needed)
Estimate: 0:45, unproven until #15
Evidence: snapshot object name and timestamp (OpenBao RPO), `bao status` output, ClusterSecretStore status

A TPM seal cannot be restored on new hardware: the key is bound to the lost TPM, so the
snapshot could never be decrypted. That is why C1 uses `seal "static"`.

1. Write the escrowed static seal key to `/etc/openbao/seal/<key-id>.key` (mode 0400, owner
   openbao) on every control-plane node with
   `deploy/enterprise/openbao/ansible/seal-key.yml` (see [openbao.md](openbao.md)).
2. Deploy OpenBao from IaC (`deploy/enterprise/openbao/`, #4) with the matching stanza,
   `seal "static" { current_key_id = "<key-id>" current_key = "file:///openbao/seal/<key-id>.key" }`
   (the pods mount `/etc/openbao/seal` read-only at `/openbao/seal`), where `<key-id>` is the
   escrowed key id that was current when the snapshot was taken.
3. Initialise the new cluster, then download the newest raft snapshot from the offsite
   OpenBao prefix (A1) and record its timestamp.
4. Restore it: `bao operator raft snapshot restore -force <snapshot-file>`.
5. Restart the pods and check auto-unseal: `bao status` shows `Sealed false` with seal type static.
6. If a root token is needed, generate it with the Shamir recovery key holders
   (`bao operator generate-root`), and revoke it at the end of the step.
7. Check External Secrets: `kubectl get clustersecretstore` shows the `ClusterSecretStore` Ready.

Done when: OpenBao is unsealed by the static seal and the ESO `ClusterSecretStore` is Ready.

### Step 4: Rook-Ceph on fresh OSDs

Depends on: 3
Owner role: Platform admin
Estimate: 1:00, unproven until #15
Evidence: `ceph status` showing HEALTH_OK, OSD count, pool list

1. Wipe the replacement NVMe disks; never reuse the old cluster's OSDs or `fsid`.
2. Deploy Rook-Ceph from IaC (#3, ADR-0033) with OSD encryption by dm-crypt, keys kept in the
   restored OpenBao (#20, ADR-0061).
3. Apply the OSD reservations and recovery throttles (ADR-0055).
4. Wait for `ceph status` to report `HEALTH_OK`.
5. Create the CephFS, RBD and RGW pools and the storage classes from IaC.

Done when: `HEALTH_OK`, all OSDs up and in, pools and storage classes present.

### Step 5: Images and Harbor

Depends on: 3, 4
Owner role: Platform admin
Estimate: 1:00 (parallel with steps 6-7), unproven until #15
Evidence: CI pipeline IDs, image digests, cosign verify output, Kyverno admission check

1. Deploy Harbor (#5) from IaC.
2. Re-run the federal GitLab CI pipelines for the 3-5 golden images (ADR-0028) and the
   platform image mirror.
3. Sign with the cosign key from OpenBao (ADR-0029) and check `cosign verify` per image.
4. Check Kyverno admits a signed test pod and rejects an unsigned one.

Done when: all golden and platform images are in Harbor, signed and admitted by Kyverno.

### Step 6: CNPG point-in-time recovery

Depends on: 3, 4
Owner role: Platform admin
Estimate: 0:45, unproven until #15
Evidence: recovery target time, last WAL time restored (CNPG RPO), row counts per table vs pre-incident metric

1. Install the CNPG operator and barman-cloud plugin from IaC (#24, ADR-0036).
2. Create an `ObjectStore` pointing at the offsite barman-cloud prefix (A1), credentials from OpenBao.
3. Create the new Styx and Keycloak `Cluster` objects with `bootstrap.recovery` from that
   ObjectStore. For PITR set the target time in UTC with an explicit `Z`, for example:

   ```yaml
   bootstrap:
     recovery:
       source: origin
       recoveryTarget:
         targetTime: "2026-11-10T03:00:00Z"
   ```

   Omit `recoveryTarget` to replay to the end of the archived WAL.
4. Wait for both clusters to be healthy (`kubectl cnpg status`).
5. Record row counts for the key tables (users, groups, instances, Keycloak realm users) and
   compare with the last pre-incident metric.

Done when: both clusters are healthy and row counts match or the gap is explained in the log.

### Step 7: Velero restore of app namespaces

Depends on: 4, 5, 6
Owner role: Platform admin
Estimate: 0:45, unproven until #15
Evidence: backup name and timestamp (Velero RPO), restore name, `velero restore describe` result

1. Install Velero from IaC with the offsite BSL (A1) and the escrowed repo password in the
   `velero-repo-credentials` secret.
2. Check `velero backup-location get` shows the BSL Available and list backups.
3. Restore the newest good backup and exclude the platform pieces rebuilt above:
   `velero restore create --from-backup <backup> --exclude-namespaces rook-ceph,openbao,kube-system --exclude-resources clusters.postgresql.cnpg.io`.
   Velero applies its default order (CRDs, namespaces, ..., PVCs, secrets, pods).
4. Check `velero restore describe <restore>` shows Completed with no errors.

Done when: app namespaces are restored and their workloads are Running.

### Step 8: Homes and profiles from Kopia

Depends on: 1, 4
Owner role: Platform admin
Estimate: data/WAN bound (see window below), unproven until #15
Evidence: snapshot IDs and times (Kopia RPO), `kopia snapshot verify` output, sampled file hashes, per-group finish times

Window for 2 TB (150-200 users at 10 GB): about 4.5 h at 1 Gbit/s and about 9 h at
500 Mbit/s sustained. Only priority homes count toward T_end (D1).

1. Connect read-only to the #13 repository with the escrowed Kopia password:
   `kopia repository connect s3 --readonly --bucket=<b> --endpoint=<e> --region=<r> --prefix=<p>`.
2. Create fresh CephFS subvolumes with the same group layout and quotas (ADR-0034, ADR-0054).
3. Restore in priority order: admins, help desk, then by group (help desk keeps the order).
   Per subvolume: `kopia snapshot restore <snapshot-id> <subvolume-path>`.
4. Fix ownership to the immutable POSIX UIDs (ADR-0052).
5. Run `kopia snapshot verify` and compare sampled file hashes.

Done when: priority homes are restored before step 10; the rest finish by priority after T_end.

### Step 9: Smoke test

Depends on: 6, 7
Owner role: Help desk + ISSO
Estimate: 0:45, unproven until #15
Evidence: pass/fail per check with time and tester, screenshots

1. Banner shows before login (ADR-0027).
2. CAC login works with OCSP reachable (ADR-0017).
3. Desktop launch works and a file in a restored priority home is present.
4. Provisioning webhook mTLS call succeeds.
5. Break-glass login works and raises an alert.

Done when: every check passes or the incident commander accepts the deviation in the log.

### Step 10: Cutover and declare service restored

Depends on: 9
Owner role: Incident commander
Estimate: 0:15, unproven until #15
Evidence: T_end, RTO, RPO per data set, DNS change record, user notice

1. Switch DNS and the DMZ to the rebuilt site.
2. Declare service restored and record T_end in UTC.
3. Record RTO = T_end − T0 and RPO per data set (see [Evidence](#evidence)).
4. Notify users; help desk publishes the remaining home-restore schedule.
5. Custodians reseal the escrow envelope and log the new seal numbers.

Done when: T_end, RTO and RPO are recorded and users are notified.

## Control-plane-only loss

Use an RKE2 etcd snapshot restore **only** when the control plane is lost and the site
(workers, Ceph disks, network) is intact. It is never part of a full-site rebuild: it brings
back stale Node, PV and Rook CephCluster objects (old fsid, mon secrets, OSD keys) that do not
match fresh disks.

1. Stop RKE2 on all server nodes.
2. On one server: `rke2 server --cluster-reset --cluster-reset-restore-path=<snapshot-path>`.
   This needs the **original** RKE2 token from the escrow envelope.
3. Start RKE2 on that node, then rejoin the other servers after removing their old etcd data.
4. Log it in the evidence log the same way as a full restore.

## Evidence

Each restore (real or test) produces two files under `docs/enterprise/evidence/dr/<date>/`:
a JSON step log with the same schema as the #15 harness, and a Markdown report rendered from it.

Step log (`steps.json`, all times UTC):

```json
{
  "schema_version": "1.0",
  "steps": [
    {
      "id": "3",
      "start": "2026-11-10T02:15:00Z",
      "end": "2026-11-10T03:00:00Z",
      "actor": "<platform admin>",
      "command": "bao operator raft snapshot restore -force <snapshot-file>",
      "result": "ok"
    }
  ]
}
```

The Markdown report (`report.md`) covers:

- **RTO** achieved: T_end − T0, with any deviations from this runbook.
- **RPO** per data set: incident time minus the newest restored backup, for CNPG, Velero,
  Kopia homes and the OpenBao snapshot.
- **Integrity:** DB row counts per table vs the pre-incident metric, `kopia snapshot verify`
  output, sampled file hashes, smoke-test results.
- **Escrow:** seal numbers broken and resealed, with both custodians.
- **Lessons learned** and gaps, each with an owner and a ticket.
- **Sign-off** by the ISSO and the incident commander.

Attach the report to eMASS controls CP-4, CP-9, CP-10 and risk acceptance R03. The full-site
restore test repeats annually (CP-4).

## Follow-up IaC

Reference only; built in other tickets, not here:

- #24 CNPG ObjectStore pointed at the offsite bucket prefix (A1). Barman-cloud only offers
  server-side encryption, so record an SC-28 note.
- Velero offsite BSL; replace the default repo password before the first backup (it cannot change later).
- OpenBao raft snapshot CronJob writing nightly to the offsite prefix.
- RGW cold-archive mirror to the offsite bucket (ADR-0035).
- CNPG volumeSnapshot backups kept locally on Ceph for fast local restores.
- The static seal (`seal "static"`) in #4, with the key and its key id escrowed in both sets (C1).
