# Kubernetes enterprise overlay

The overlay in `deploy/enterprise/` runs Styx on a CloudNativePG (CNPG)
Postgres cluster with offsite backups. It builds on
[Kubernetes](kubernetes.md) and sets the backend to 3 replicas.

## Prerequisite operators

| Component | Version | Purpose |
|---|---|---|
| CloudNativePG | 1.30.x | Postgres cluster `styx-db`, backups |
| barman-cloud plugin | 0.16.x | WAL archive and base backups to the object store |
| cert-manager | current | Required by the barman-cloud plugin |
| External Secrets Operator (ESO) | current | Syncs DB credentials and bucket keys from OpenBao |
| Reloader | current | Restarts backend pods when a Secret changes |

## First boot: setup code

The setup token lives in the database (`setup_tokens`, a singleton row created
with `INSERT ... ON CONFLICT DO NOTHING`), so all replicas share one code and it
is consumed exactly once. Read it from any pod log (`setup code`) and finish setup
in the browser; no need to scale down first.

Set `JWT_SECRET` in `styx-secrets`. If it is unset each pod writes its own
`/app/data/secrets.json` and tokens fail across replicas (styx-portal#85 will make
an unset `JWT_SECRET` a startup error).

## Forced credential rotation

The `styx-db-app` password is rotated from OpenBao via ESO every 30 days
(NIST IA-5; configurable via the ExternalSecret `refreshInterval`); CNPG applies
the updated Secret to the role.

!!! note
    This section assumes the `styx-db-app` ExternalSecret and the Reloader
    annotation on `deploy/backend` are provisioned. They are not yet in
    `deploy/enterprise` or `deploy/k8s`; do not run `kubectl annotate` until they exist.

To rotate now, bump the `force-sync` annotation on the ExternalSecret:

```bash
kubectl -n styx annotate externalsecret styx-db-app \
  force-sync="$(date +%s)" --overwrite
```

Wait for Reloader to restart the pods, then check the new password works with a
real DB query (the command does not print the secret):

```bash
kubectl -n styx get secret styx-db-app -o jsonpath='{.metadata.resourceVersion}'
kubectl -n styx rollout status deploy/backend
kubectl -n styx exec deploy/backend -- python -c "import asyncio,os;from sqlalchemy import text;from sqlalchemy.ext.asyncio import create_async_engine as c
async def m():
    async with c(os.environ['DATABASE_URL']).connect() as k: await k.execute(text('select 1'))
    print('db ok')
asyncio.run(m())"
```

Expect a rotation gap: new connections from a pod still holding the old
password fail until it has the new one (Secret volume refresh takes about
60-90 s, then Reloader restarts the pod). `/api/health` does not touch the DB,
so do not use it to confirm the password. Also check
`kubectl -n styx logs deploy/backend` for DB errors.

## Restore

**From barman (offsite).** Follow the
[full-site restore runbook](../enterprise/runbooks/full-site-restore.md). The SSE-C key
must never change for the life of the backups; keep it escrowed in OpenBao and in both
escrow sets (B1). If the provider lacks SSE-C, use SSE-KMS.

**From a snapshot.** Nightly `styx-db-snapshot-daily` produces volume snapshots.
Create a new `Cluster` with `bootstrap.recovery.volumeSnapshots.storage`
referencing the snapshot (`kubectl -n styx get volumesnapshot`). Give it the same
name `styx-db` as the original (delete the broken Cluster first) so the `styx-db-rw`
service and `styx-db-app` secret the backend uses stay valid. Apply it before the
rest of `deploy/enterprise`, then scale the backend to 1, then 3.

## Migrations: expand/contract

With several replicas, old and new pods run side by side during a rollout.
Every Alembic migration must therefore be backward compatible with the previous release:

1. **Expand**: add columns/tables as nullable or defaulted; release N writes both.
2. **Contract**: drop or tighten in release N+1, after N is fully rolled out.

Never rename or drop in the same release that stops using the old shape.

## Known limits

- Per-pod `emptyDir`: screenshots, the artifact cache and LAN certs are per-pod (accepted in #23).
- `/api/health` does not touch the DB.
- Out of scope here: pooler, DDL/DML role split (later AC-6 hardening).
