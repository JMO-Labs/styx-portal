# Session audit events

Styx writes one ECS JSON line per session lifecycle step to the dataset `styx.audit` (existing index template, ILM `styx-logs`; see [logging](../operate/logging.md)). Decision record: [ADR-0072](adr/0072-session-lifecycle-audit-events.md). Controls: AU-2, AU-3, AU-12 in the [control matrix](control-matrix.md).

## Catalogue

| `event.action` | `event.type` | Emitter | Fires when | Extra fields |
|---|---|---|---|---|
| `session.launch` | `start` | backend | an instance is created or started, or a workstation stream is opened | |
| `session.connect` | `start` | agent, via backend | a viewer attaches to the stream | `styx.session.viewer_id` |
| `session.disconnect` | `end` | agent, via backend | a viewer detaches | `styx.session.viewer_id` |
| `session.lock` | `change` | backend | the instance is paused, or the gateway reports it locked | |
| `session.unlock` | `change` | backend | the instance is unpaused, or the gateway reports it unlocked | |
| `session.stop` | `end` | backend | the session ends for any reason below | `styx.session.reason` |

Backend emitters: `routers/instances.py`, `services/session_monitor.py`, `services/session_reaper.py`, `services/offboarding.py`, `services/cve_recycle.py`. Agent viewer events travel in the heartbeat (`health.session_events`) and are written by `routers/agent.py`. Builder: `session_event()` in `backend/app/services/audit_ecs.py`.

## Fields

| Field | ECS mapping | Type | Notes |
|---|---|---|---|
| `event.dataset` | ECS | keyword | always `styx.audit` |
| `event.action` | ECS | keyword | one of the six actions |
| `event.category` | ECS | keyword[] | `["session"]` |
| `event.type` | ECS | keyword[] | `start`, `end` or `change` as in the table |
| `event.outcome` | ECS | keyword | `success` |
| `user.id`, `user.name` | ECS | keyword | session owner |
| `host.name` | ECS | keyword | node running the session |
| `container.image.hash.all` | ECS | keyword[] | image digest |
| `styx.session.id` | custom | keyword | instance id, or workstation id for workstation streams |
| `styx.session.kind` | custom | keyword | `instance` or `workstation` |
| `styx.session.reason` | custom | keyword | `session.stop` only |
| `styx.session.viewer_id` | custom | keyword | connect and disconnect only |
| `styx.session.groups` | custom | keyword[] | names of the user's groups, i.e. the group policy in effect |

Empty fields are omitted from the line.

## Stop reasons

| `styx.session.reason` | Meaning |
|---|---|
| `user` | the owner stopped the session |
| `deleted` | the instance was deleted (destroyed) |
| `idle` | the idle monitor stopped it (ADR-0039) |
| `max_duration` | the maximum session length was reached (ADR-0039) |
| `offboarded` | the user was offboarded or disabled |
| `cve_recycle` | recycled to pick up a patched image |

!!! note
    The session reaper also stops sessions that were disconnected longer than `SESSION_DISCONNECT_MAX_H` (ADR-0039) and currently writes `disconnected` as the reason. It is not in the list above, so a consumer should treat unknown reasons as valid.
