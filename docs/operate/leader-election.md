# Leader election and multi-replica operation

With more than one backend replica, background loops (janitor, health, metrics, boot steps) run on exactly one replica, the **leader**. Leadership is a session-level Postgres advisory lock held on one dedicated connection. Design: [ADR-0056](../enterprise/adr/0056-styx-postgres-migration-alembic-leader-election-cnpg-roles.md).

!!! warning "SQLite means `replicas: 1`"
    On SQLite the elector is a stub that is always leader. Two replicas would both run every loop. Run SQLite deployments with a single replica.

## Settings

Environment variables (not live-editable in Admin → Settings).

| Variable | Default | Meaning |
|---|---|---|
| `LEADER_DATABASE_URL` | empty (= `DATABASE_URL`) | Connection used only for the lock. Must reach the Postgres **primary directly**. |
| `LEADER_RETRY_S` | `5` | Candidate retry interval. |
| `LEADER_HEARTBEAT_S` | `5` | Leader heartbeat interval (checks it still holds the lock). |
| `LEADER_HEARTBEAT_TIMEOUT_S` | `3` | Timeout for a single lock or heartbeat query. |
| `LEADER_FENCE_S` | `15` | Leader steps down after this long without a successful heartbeat. |
| `BAN_CACHE_TTL` | `30` | Max staleness of the per-replica IP ban cache. |

Constraints:

- **No pooler in front of the elector.** PgBouncer (transaction mode) or any pooler silently breaks session locks. Point `LEADER_DATABASE_URL` at the CNPG `-rw` service or primary.
- **`LEADER_FENCE_S` must stay shorter than the keepalive total** (idle 10 s + 3 x 5 s interval, `tcp_user_timeout` 20 s, about 25 s). Otherwise a partitioned leader keeps acting after another replica wins.
- Leadership is **not** part of the readiness probe. Every replica serves traffic; `/api/system/diagnostics` report `leader` for information only.

## Who is leader

```sql
SELECT pid, client_addr, backend_start
FROM pg_locks l JOIN pg_stat_activity a USING (pid)
WHERE locktype = 'advisory' AND granted AND classid = 0x5354;
```

One row is expected. Match `client_addr` to a pod IP (`kubectl get pod -o wide`). Zero rows for longer than the failover time below means no leader; check the backend logs for `leader acquired` / `leader lost`.

## Failover times

| Event | Leader gap |
|---|---|
| Rolling restart / SIGTERM | <= 5 s (lock released on shutdown, next retry takes it) |
| Leader process crash, node alive | <= 5 s (server drops the session) |
| Node loss / network partition | ~25-30 s (keepalive / `tcp_user_timeout`) |
| CNPG primary failover | CNPG failover time + <= 5 s |

Request serving is unaffected during a gap; only leader-only loops pause.

## Shared abuse state

Lockouts, IP failure counts and bans live in Postgres and are shared. Each replica caches active bans in memory and refreshes every `BAN_CACHE_TTL` seconds, so a ban written on one replica can take up to that long to apply on another. The writing replica applies it immediately.

## Metrics across replicas

Every replica serves its own `/metrics` port; Prometheus scrapes them all. Each series is either leader-owned or per replica:

| Metric | Owner | Aggregate with |
|---|---|---|
| `styx_instances{status}`, `styx_stream_sessions_active` | Leader only (DB-derived; non-leaders export nothing) | `max` or `sum` (one series) |
| `styx_http_request_duration_seconds` | Per replica (requests that replica served) | `sum` |
| `styx_launch_duration_seconds`, `styx_launch_failures_total`, `styx_instance_launch_*` | Per replica (launches that replica handled) | `sum` |
| `styx_stream_rtt_seconds` | Per replica (client reports that replica received) | `sum` |
| `styx_slo_business_hours`, `styx_maintenance_active` | Per replica (config-derived, identical) | `max` |

The scrape's `instance`/`pod` target label tells replicas apart; no extra `replica` label is added. Service health checks run only on the leader and are stored in the DB, so every replica serves the same health state. During failover the leader-owned gauges are absent for up to one election cycle.

Known gaps, tracked as follow-ups: `settings_store` cache is per replica.
