# ADR-0080: Session timeouts implementation

- Status: Proposed
- Date: 2026-11-14
- Decision ID: D79
- Related controls: AC-11, AC-12, SC-10

## Context

ADR-0039 fixed the timeouts (15 min idle lock, 2 h disconnect stop, 12 h max) and risk R02. This record says how they are built. Audit events are in [session-events.md](../session-events.md) (ADR-0072); the operator view is the [session-timeouts runbook](../runbooks/session-timeouts.md).

## Decision

- **Idle lock, 15 min.** The Styx gateway in the desktop pod locks the session after `STYX_LOCK_IDLE_S` seconds without input (`agent/gateway_idlelock.py`). The portal sets it at launch from the owner's groups; it defaults to 900 s. Locked means the gateway answers 423, closes its websockets with code 4003 and the patched Selkies withholds video (ADR-0078). The session keeps running.
- **Per-group override, capped.** `idle_lock_minutes` on a group; the smallest value across the user's groups wins. In the enterprise profile it is capped at 15 (1 to 15, else 422), so a group can only shorten the lock. Templates and owners cannot set `STYX_LOCK_IDLE_S`.
- **Fresh-handshake unlock, no TLS resumption.** `GET /api/instances/{id}/unlock` needs the HAProxy verified-card header (`Client-Cert`), so a new TLS handshake with the card is required. HAProxy has resumption off (`no-tls-tickets`, `tune.ssl.cachesize 0`, ADR-0065), so a resumed session cannot pass. The portal then redirects to the gateway with a 60 s HMAC token (key derived per instance from `JWT_SECRET`). This proves the card is present, not PIN entry (R02).
- **2 h disconnect stop.** The leader-only session reaper stops an instance with no connections for `SESSION_DISCONNECT_MAX_H` (default 2) hours. Stop reason `disconnected`.
- **12 h max.** The reaper stops an instance `SESSION_MAX_H` (default 12) hours after `started_at`, reason `max_duration`. A notice is posted `SESSION_WARN_MIN` (default 15) minutes before.
- **Audit.** `session.lock`, `session.unlock` (gateway state seen by the reaper, and the unlock endpoint), `session.unlock_denied` (reason `no_card` or `not_owner`), and `session.stop`.

## Alternatives considered

- Lock in the browser: rejected, a client can ignore it.
- Stop the pod on idle instead of locking: rejected, users lose work (see ADR-0039).
- A longer cap for some groups: rejected, AC-11 needs 15 min or less.

## Consequences

- The lock is only as fresh as the gateway; the reaper sees lock state on its next pass.
- The 2 h and 12 h limits are global settings, not per group.
- Card removal still locks only through managed-endpoint policy (R02).
