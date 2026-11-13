# ADR-0072: Session lifecycle audit events

- Status: Proposed
- Date: 2026-11-13
- Decision ID: D71
- Related controls: AU-2, AU-3, AU-12

## Context

ADR-0039 fixed the session timeouts and ADR-0044 the audit shipping. Neither says which session events are logged, nor how they are keyed. The catalogue is in [session-events.md](../session-events.md).

## Decision

- **Dataset reused.** Session events go to `styx.audit`, with the existing index template and ILM `styx-logs`. No new dataset, no new retention.
- **Session id.** `styx.session.id` is the instance id, or the workstation id for workstation streams. `styx.session.kind` says which (`instance` or `workstation`). No separate session table key is introduced.
- **Lock and unlock.** `session.lock` and `session.unlock` are the pause and unpause of the instance (and the gateway lock state, where reported).
- **Group policy.** `styx.session.groups` lists the user's group names at the time of the event. That is the group policy in effect (ADR-0038, ADR-0070), without copying the policy values.
- **Connect and disconnect via heartbeat.** The agent reports viewer connect and disconnect in the heartbeat; the backend writes the lines. No new agent-to-backend endpoint, and delivery is at heartbeat granularity.
- **Stop reasons.** `user`, `deleted`, `idle`, `max_duration`, `offboarded`, `cve_recycle`.

## Alternatives considered

- A new dataset `styx.session`: rejected, it needs a new template and retention for no gain.
- Agent writes the lines itself: rejected, the agent has no log shipper and the backend already owns identity and groups.

## Consequences

- Connect and disconnect times can lag by up to one heartbeat.
- Group names are copied into each event, so later group changes do not rewrite history.
