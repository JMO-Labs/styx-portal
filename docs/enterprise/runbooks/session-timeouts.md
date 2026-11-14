# Session timeouts runbook

Controls: AC-11, AC-12, SC-10. Decisions: ADR-0039, ADR-0080. Audit catalogue: [session-events.md](../session-events.md).

## Timeouts

| Rule | Value | Where set |
|---|---|---|
| Idle lock | 15 min default (900 s) | group `idle_lock_minutes`, passed to the pod as `STYX_LOCK_IDLE_S` |
| Disconnect stop | 2 h | `SESSION_DISCONNECT_MAX_H` (backend setting) |
| Max session | 12 h | `SESSION_MAX_H` (backend setting) |
| Max-session warning | 15 min before | `SESSION_WARN_MIN` |

## Config keys

- **Per-group override.** Set `idle_lock_minutes` on the group (group create or update API). The smallest value across a user's groups applies. In the enterprise profile it must be 1 to 15; 0 or more than 15 returns 422. It is capped at 15 min, so it can only shorten the lock. Empty means 15.
- **Takes effect at launch.** The value is written into the pod env as `STYX_LOCK_IDLE_S`. Running sessions keep the old value until they restart. Templates and owner overrides cannot change it.
- **Reaper.** `SESSION_DISCONNECT_MAX_H`, `SESSION_MAX_H` and `SESSION_WARN_MIN` are backend env settings; change them only with a new ADR.

## Unlock

The user opens the lock page and chooses Unlock. The portal needs a fresh TLS handshake with the card (no resumption), then redirects to the gateway with a 60 s token. This proves card presence, not PIN entry (R02).

## Audit events

Dataset `styx.audit`:

| `event.action` | Meaning |
|---|---|
| `session.lock` | the gateway reported the session locked |
| `session.unlock` | the unlock endpoint minted a token, or the gateway reported unlocked |
| `session.unlock_denied` | refused; `detail.reason` is `no_card` or `not_owner` |
| `session.stop` | `styx.session.reason` is `disconnected` (2 h) or `max_duration` (12 h) |

## Troubleshooting

- **Never locks.** Check the pod env: `STYX_LOCK_IDLE_S` must be above 0; `styx-start` (`images/enterprise-base`) maps it to the gateway's `STYX_GW_LOCK_IDLE_S`. Relaunch to pick up a group change.
- **Group change rejected (422).** The value is outside 1 to 15 in the enterprise profile.
- **Unlock returns 403 `no_card`.** The request had no `Client-Cert` header: the browser resumed a TLS session or sent no card. Close the browser, reinsert the card and retry. If it repeats for everyone, check that HAProxy still has `no-tls-tickets` (ADR-0065).
- **Unlock returns 403 `not_owner`.** Only the owner or an admin can unlock.
- **Token expired.** Tokens last 60 s; start the unlock again.
- **No `session.lock` events.** The reaper only logs a change when it reaches the gateway state endpoint; look for "gateway state unreachable" in the backend log. Only the leader replica runs the reaper.
- **Session stopped unexpectedly.** Read `styx.session.reason`: `disconnected` after 2 h without a viewer, `max_duration` at 12 h. Users get a notice 15 min before the 12 h limit.
