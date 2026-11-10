# DR restore test harness

`deploy/dr/restore-test/styx_drtest.py` restores Styx data into a **scratch** target
and checks it. It covers the phase-1 full-site restore exit test (ADR-0037) and the
annual repeat (R03), as evidence for CP-4, CP-9 and CP-10. It is a Python CLI that
uses only the standard library. It calls `kubectl`, `velero`, `kopia`, `psql` and
`pg_amcheck` with argv lists, never through a shell (issue #15).

Status: code and tests only, not run yet (IaC done, not run).

| Restorer | Source | Restores into |
|---|---|---|
| CNPG | barman-cloud object store (`serverName`) | a **new** `Cluster` with `bootstrap.recovery` in the scratch namespace |
| Velero | a backup on a **ReadOnly** BSL | the scratch namespace(s) through `--namespace-mappings` |
| Kopia | the offsite repository from [Offsite backup](offsite-backup.md) (#13) | paths under `scratch_mount_root` |

Each section (`cnpg`, `velero`, `kopia`) is optional. Leave it out of the config to skip it.

## Usage

```bash
cd deploy/dr/restore-test
export KUBECONFIG=~/.kube/styx-drtest          # least-privilege, see below
export PGPASSWORD=...                          # restored and source DB (read-only role)
export KOPIA_PASSWORD=... AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...   # read-only key
export DRTEST_CNPG_S3_KEY_ID=... DRTEST_CNPG_S3_SECRET=...                  # read-only key

./styx_drtest.py -c drtest.json fingerprint      # at the recovery target time, on the source DB
./styx_drtest.py -c drtest.json mark T0 start    # full-site only: start of the RTO clock
./styx_drtest.py -c drtest.json mark rke2 start  # any manual runbook step (#14)
./styx_drtest.py -c drtest.json mark rke2 end
./styx_drtest.py -c drtest.json plan             # guards + print every write, change nothing
./styx_drtest.py -c drtest.json run --confirm 2026-q4-drill
./styx_drtest.py -c drtest.json report           # rebuild the report (for example after more marks)
./styx_drtest.py -c drtest.json teardown --confirm 2026-q4-drill
```

| Command | Writes |
|---|---|
| `plan` | nothing. Runs the guards (reads only) and prints every command and manifest `run` would apply. |
| `run --confirm <run-id>` | without a matching `--confirm` it exits non-zero and writes nothing. Creates the scratch namespace(s), restores, checks, writes the report. |
| `fingerprint [--out f]` | the baseline JSON file only. Its SQL is `SELECT` only, in a `default_transaction_read_only` session. |
| `mark <step-id> start\|end [--actor x]` | one line in the run's `steps.jsonl` |
| `report` | `report.json` and `report.md` |
| `teardown --confirm <run-id>` | deletes the scratch namespace(s) that carry `styx.io/dr-run=<run-id>` and pass Guard 2 |

Exit codes: 0 pass, 1 the run finished but did not pass, 2 refused (guard, config or
`--confirm`), with nothing written.

Teardown leaves the Velero `Restore` object (a record in the `velero` namespace) and the
Kopia files under `scratch_mount_root`. Remove the files by hand after the report is filed.

## Configuration

Copy `drtest.example.json`. The config holds **no secrets**. A key that looks like a
secret (`password`, `secret`, `token`, `access_key`, `key_id`, `credential`) is refused.
Secrets come only from the environment variables above.

| Key | Meaning |
|---|---|
| `run_id` | `^[a-z0-9][a-z0-9-]{0,40}$`; also the `--confirm` value and the `styx.io/dr-run` label |
| `mode` | `data-only` (T0 = harness start) or `full-site` (T0 = `mark T0 start`) |
| `namespace` | scratch namespace, `styx-drtest-...` |
| `prod_cluster_uids` / `scratch_cluster_uids` | `kube-system` namespace UIDs (`kubectl get ns kube-system -o jsonpath='{.metadata.uid}'`) |
| `operator`, `witness`, `rto_clock_start` | copied into the report (`rto_clock_start` is the #14 D1 wording) |
| `incident_time` | RPO reference, ISO 8601 with zone; default: run start |
| `evidence_root` | default `evidence/dr` |
| `alembic_head` | expected Alembic head revision of the restored DB |
| `health_url`, `health_attempts`, `health_interval_s` | `GET /api/health` of the restored backend, retried until 200 |
| `cnpg.server_name`, `cnpg.cluster_name` | source `serverName` in the object store; new cluster name (must differ) |
| `cnpg.object_store` | `destination_path`, `endpoint_url` of the barman-cloud store |
| `cnpg.target_time` | optional PITR time; must end in `Z` or `+00:00`. Use the fingerprint time. |
| `cnpg.source`, `cnpg.restored` | libpq `host`, `port`, `user`, `dbname` (password from `PGPASSWORD`) |
| `cnpg.tables` | `{table: primary-key column(s), comma-separated}` to fingerprint |
| `velero.backup`, `velero.prod_bsl` | the backup to restore; the production BSL name (refused) |
| `velero.include_namespaces`, `velero.namespace_mappings` | every included namespace must map to a `styx-drtest-*` namespace |
| `kopia.s3` | `bucket`, `endpoint`, `prefix`, optional `region`, `disable_tls` |
| `kopia.scratch_mount_root`, `kopia.sources[]` | restore root; `{source: "styx@offsite:/export/<group>/<subvol>", target: path}` |
| `kopia.sample` | number of restored files whose sha256 is compared with the repository |

## Guards

All guards run before the first write. A refusal exits 2 with a `REFUSED:` message and
nothing has been created. The guards are defence in depth. The least-privilege kubeconfig
and the read-only keys below are the primary control.

1. **Cluster.** Reads the `kube-system` UID. Refuses a UID in `prod_cluster_uids`. In
   `full-site` mode it also refuses a UID that is not in `scratch_cluster_uids`.
   Option A (below) runs in the production cluster, so that cluster must not be listed in
   `prod_cluster_uids` for an option A run. Guards 2 to 5 and RBAC then carry the safety.
2. **Namespace.** Must match `^styx-drtest-[a-z0-9-]+$`. `styx`, `default`, `kube-*`,
   `cnpg-*`, `velero`, `openbao`, `rook-ceph` and `styx-backup` are always refused. The
   harness creates the namespace (`kubectl create`, which fails if it exists) with
   `styx.io/dr-scratch=true` and `styx.io/dr-run=<run-id>`. It refuses an existing
   namespace that lacks its own run label.
3. **Velero.** `--include-cluster-resources=false` always. `--namespace-mappings` must
   cover every included namespace (Velero restores unmapped namespaces in place); `*` is
   refused. The backup's BSL must be `accessMode: ReadOnly` and must not be `prod_bsl`:
   create a separate ReadOnly BSL on the same bucket, never patch the production one.
4. **CNPG.** The `Cluster` has `bootstrap.recovery`, **no** `spec.plugins` and **no**
   `spec.backup` (it must never archive WAL into the production store). Its name differs
   from `serverName`, and `targetTime` is UTC.
5. **Kopia.** `repository connect` always has `--readonly` (and `--no-persist-credentials`,
   with a per-run `--config-file`). Restore targets must resolve (realpath, through `..`
   and symlinks) strictly inside `scratch_mount_root`.

No secret from the environment is printed or written: every output path redacts the
values of variables whose name contains `PASS`, `SECRET`, `TOKEN`, `ACCESS_KEY`, `KEY_ID`
or `CREDENTIAL`.

## Least privilege

**Kubeconfig.** Use a dedicated ServiceAccount, not an admin context:

- a ClusterRole with `get` on `namespaces` and `create` on `namespaces` (Kubernetes cannot
  restrict namespace creation by name, so pair it with an admission policy that only
  allows `styx-drtest-*` names), plus `delete` on namespaces for teardown;
- RoleBindings, only inside `styx-drtest-*` namespaces, for `secrets`, `clusters` and
  `objectstores` (create, get, apply, watch) and read access to pods and services;
- in the `velero` namespace: `get` on `backups` and `backupstoragelocations`, `create`
  and `get` on `restores`. Nothing else.

**S3 keys.** The CNPG (`DRTEST_CNPG_S3_*`) and Kopia (`AWS_*`) keys only allow
`s3:GetObject` and `s3:ListBucket` on the backup buckets. They are not the export or
archive keys.

**Database.** The `fingerprint` role on the source DB only needs `SELECT` on the listed
tables.

## Checks, RTO and RPO

| Data set | Check | Pass |
|---|---|---|
| CNPG | per table `count(*)` and `md5(string_agg(t::text, '' ORDER BY <pk>))` | equal to the `fingerprint` baseline |
| CNPG | `pg_amcheck --heapallindexed` | exit 0 |
| CNPG | `alembic_version` | equals `alembic_head` |
| Velero | restore phase | `Completed`, 0 errors |
| Kopia | `snapshot verify --verify-files-percent=100` on the newest snapshot | exit 0 |
| Kopia | sha256 of `sample` restored files vs `kopia show` of the same file | all equal |
| App | `GET health_url` | 200 |

- **RTO** = time of the last passing health check minus T0. Pass if at most 8 h.
- **RPO** per data set = `incident_time` minus the newest recovered point. Pass if at
  most 24 h. The point is `pg_last_xact_replay_timestamp()` (CNPG), the backup
  `.status.startTimestamp` (Velero) or the snapshot `startTime` (Kopia).
- The run passes only if every check, the RTO and every RPO pass.

## Evidence

`evidence/dr/<YYYY-MM-DD>-<run-id>/` holds `steps.jsonl` (append-only step log),
`state.json`, `report.json` and `report.md`. `report.json` (`schema_version` `"1.0"`):

| Field | Content |
|---|---|
| `run_id`, `mode`, `target{cluster_uid,namespace}` | what was restored where |
| `operator`, `witness`, `git_sha`, `tool_versions` | who, and which harness and tools |
| `rto_clock_start`, `t0`, `t_end`, `incident_time` | clock inputs |
| `steps[]{id,start,end,actor,command,result}` | harness commands (redacted) and manual marks |
| `datasets[]{source,backup_id,recovered_point,rpo_seconds,checks[]{name,pass,detail}}` | `source` is `cnpg`, `velero`, `kopia:<source>` or `app` (health; no RPO) |
| `rto_seconds`, `rto_limit_seconds`, `rpo_limit_seconds`, `pass` | the verdict |
| `controls` | `["CP-4","CP-9","CP-10","R03"]` |
| `log_sha256` | sha256 of `steps.jsonl` |

The ISSO signs `report.md` before it is filed in eMASS.

## Where to run it

| Option | Mode | Use | Trade-off |
|---|---|---|---|
| A. scratch namespace in the production cluster | `data-only` | routine and annual data-path drills | cheap and repeatable; not a full-site test (reuses live Ceph, OpenBao, operators) |
| B. separate scratch cluster (temporary RKE2) | `full-site` | annual full-site repeats once hardware or VMs exist | real isolation; needs spare hardware (D06 has none) |
| C. production hardware before the pilot (wipe, then restore) | `full-site` | phase-1 exit test | most faithful; possible only once, before go-live |

Which option counts as the R03 evidence is an owner decision (with #14). It changes only
the config, not the code.

## Not in scope yet

- Writing sentinels into production (`seed`), and the `dr_heartbeat` table and CronJob.
- Real CNPG and Velero integration tests (they wait for #6 and #9). The harness is tested
  with fake binaries (`backend/tests/drtest`).
