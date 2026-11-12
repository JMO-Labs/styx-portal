# Backend required environment (Postgres)

On a PostgreSQL `DATABASE_URL` the backend refuses to start (non-zero exit, error naming `JWT_SECRET`) unless these are set:

| Variable | Why |
|---|---|
| `JWT_SECRET` | Required, at least 32 characters, identical on every replica. Without it each pod would generate its own `/app/data/secrets.json` and tokens would fail across replicas. Generate with `openssl rand -base64 48`; deliver via OpenBao / External Secrets ([runbook](openbao.md)). |
| `DATABASE_URL` | Pooled application connection. |
| `LEADER_DATABASE_URL` | Direct primary connection for leader election (never a pooler). |

SQLite (homelab) is unchanged: with `JWT_SECRET` unset the backend generates `secrets.json` under `SECRETS_FILE`.

Rotating `JWT_SECRET` logs everyone out and invalidates stored OAuth client secrets.
