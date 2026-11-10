# Upgrade

Move to a new Styx release and roll back if needed.

## Compose

Database migrations run automatically on boot.

```bash
# .env
STYX_TAG=2.7.0     # the release you want
docker compose pull && docker compose up -d
```

To roll back, set `STYX_TAG` to the previous version and repeat. Back up `secrets.json` and the data volume first ([Production](production.md#backups)). Without pinning, `latest` tracks the newest release.

After a portal upgrade, rebuild the agent artifacts so workstations get matching wheels:

```bash
scripts/build_agent_artifacts.sh ./data/artifacts
```

### One-time Alembic stamp (SQLite)

Releases from this one on manage the schema with Alembic. The first time a new
backend starts on an existing SQLite database (one without an `alembic_version`
table), it:

1. copies the database to `<db>.pre-alembic.bak` (for example
   `data/styx-portal.db.pre-alembic.bak`, mode `0600`) before any schema change;
2. runs the old built-in column migrations once, so databases that skipped
   releases get every column;
3. stamps the database at revision `0001_baseline`, then upgrades to the latest
   revision.

Later starts only run Alembic. An existing `.pre-alembic.bak` is never
overwritten. Once the new release works, you may delete it; to undo the switch,
stop the backend, roll back the image and copy the `.bak` over the database
file. Postgres databases always start from an empty schema, so there is no stamp.

## Kubernetes

Bump the `newTag` values in `deploy/k8s/kustomization.yaml`, then:

```bash
kubectl apply -k deploy/k8s
kubectl -n styx rollout status deploy/backend deploy/frontend
```

Roll back by restoring the old tag. Restore the database from `styx-backups` only if a migration went wrong ([Kubernetes](kubernetes.md#backup-restore)).

## Workstation agents

Upgrade in place with no enrollment token and no package installs:

```bash
curl -fsSL https://styx.example.com/api/enroll/script | bash -s -- --upgrade --server https://styx.example.com
```

Agents 0.9.33 to 0.9.39 added game-mode pointer lock, transport persistence, deferred settings and Xwayland fallbacks; see [Enroll workstations](workstations-enroll.md#gnome-seat). Agent 0.10.0 moves to Selkies 2.2 and needs a rebuilt wheelhouse (see [Streaming tuning](streaming-tuning.md#selkies-22-agent-0100)).

Roll back with `styx_agent.py rollback` ([details](workstations-enroll.md#upgrade-and-rollback)). Restarting the agent closes apps running in the workstation's seat, so schedule upgrades when nobody is connected.

## Versions

Releases follow semantic versioning and are published by semantic-release; the [changelog](https://github.com/JMO-Labs/styx-portal/blob/main/CHANGELOG.md) lists every change.
