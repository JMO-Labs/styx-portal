# Required secrets (Postgres / multi-replica)

| Variable | Required | Notes |
|----------|----------|-------|
| `JWT_SECRET` | **Yes** on Postgres | At least 32 chars, identical on every replica. Generate with `openssl rand -base64 48`. |

On a Postgres `DATABASE_URL` the backend exits non-zero at startup if
`JWT_SECRET` is unset, with an error naming `JWT_SECRET`. It does not fall
back to `/app/data/secrets.json`: that file is per pod, so tokens would fail
across replicas (ADR-0056).

SQLite (homelab) is unchanged: with `JWT_SECRET` unset the secret is generated
and persisted to `SECRETS_FILE`.

Provide the value through a Kubernetes Secret (or OpenBao-synced secret)
mounted as the `JWT_SECRET` env var on the backend Deployment.
