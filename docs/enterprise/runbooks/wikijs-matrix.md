# Wiki.js and Matrix runbook

Operate Wiki.js and Matrix (Synapse plus Element) from `deploy/enterprise/wikijs/`,
`deploy/enterprise/matrix/` and `deploy/enterprise/element/` (ADR-0043, ADR-0059,
[ADR-0071](../adr/0071-wikijs-and-matrix-implementation.md)).

## 1. OpenBao paths to fill

Fill these before the first sync; External Secrets (ADR-0042) reads them. Never paste values into
tickets or logs.

| Path | Properties | Used by |
|---|---|---|
| `kv/styx/wikijs/oidc` | `client_secret` | Wiki.js OIDC (Keycloak client `wikijs`) |
| `kv/wikijs/db` | `username`, `password` | Wiki.js CNPG role |
| `kv/wikijs/db-offsite` | `access_key_id`, `secret_access_key` | Wiki.js CNPG offsite backup |
| `styx/synapse/oidc` | `client-secret` | Synapse OIDC provider |
| `styx/synapse/secrets` | `macaroon`, `registration`, `signing_key` | Synapse |
| `styx/synapse/db` | `username`, `password` | Synapse CNPG role |
| `styx/synapse/db-offsite` | `access_key_id`, `secret_access_key` | Synapse CNPG offsite backup |
| `styx/matrix/notify` | `MATRIX_NOTIFY_HOMESERVER`, `MATRIX_NOTIFY_ROOM_ID`, `MATRIX_NOTIFY_TOKEN` | Backend adapter (optional) |

## 2. Wiki.js first login

Wiki.js 2 stores authentication strategies in its database. Follow the bootstrap comment at the
top of `deploy/enterprise/wikijs/deployment.yaml`: enable Generic OpenID Connect, turn on group
mapping, disable the Local strategy and remove the throwaway admin. Verify that the login page
shows only the Keycloak button.

## 3. Notification bot user, room and token

The backend adapter stays off until all three `MATRIX_NOTIFY_*` values exist.

1. Create the bot account on Synapse. Registration is disabled and login is OIDC-only, so use the
   admin API from inside the cluster (`register_new_matrix_user` with the shared secret in
   `styx/synapse/secrets` `registration`), for example user `styx-notify`. Do not print the secret.
2. Log in once as the bot (login API with its password) and copy the access token. Then discard
   the password.
3. Create a private room (no federation, no public listing) as an operator, invite the bot and
   the security officer's group, and copy the room ID (`!id:server`) from Element's room settings.
4. Write `MATRIX_NOTIFY_HOMESERVER` (the in-cluster or public Synapse URL), `MATRIX_NOTIFY_ROOM_ID`
   and `MATRIX_NOTIFY_TOKEN` to `styx/matrix/notify`. The `styx-matrix-notify` secret refreshes
   within an hour and Reloader restarts the backend.
5. Verify: trigger a test event (or use the settings page) and see the message in the room. The
   adapter logs only `matrix notify failed: <ErrorType>` on failure.

Rotate the token by logging in again as the bot, updating OpenBao and logging out the old
session. SMTP is optional (ADR-0059); nothing here needs a mail relay.

## 4. Backup coverage

- **CNPG `ScheduledBackup`:** `wikijs-db-daily` (namespace `wikijs`) and `synapse-db-daily`
  (namespace `matrix`) run daily to the offsite object store.
- **Velero:** the `daily` and `weekly` schedules in `deploy/enterprise/backup/velero-schedules.yaml`
  cover every namespace except the `excludedNamespaces` list: `rook-ceph`, `openbao`,
  `kube-system`, `velero`, `styx-backup`. `wikijs` and `matrix` are not excluded, so their
  manifests and volumes are covered. `clusters.postgresql.cnpg.io` is excluded from Velero; the
  databases are restored from CNPG backups.
- **Confirm:** `grep excludedNamespaces deploy/enterprise/backup/velero-schedules.yaml` must not
  list `wikijs` or `matrix` (a doc-lint test enforces it), and
  `kubectl -n wikijs get scheduledbackup` / `kubectl -n matrix get scheduledbackup` must show the
  daily jobs with a recent `LAST BACKUP`.

Restore follows [full-site-restore.md](full-site-restore.md).
