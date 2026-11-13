# ADR-0070: DLP policy enforcement and event shipping

- Status: Proposed
- Date: 2026-11-13
- Decision ID: D69
- Related controls: AC-4, SC-7, AU-2, AU-12

## Context

ADR-0038 fixed the DLP defaults and the per-group override rule. This ADR records the implementation choices made in the sibling PRs (#226 to #231): data model, conflict rule, enforcement points, and event shipping.

## Decision

**Fields.** Each group has six nullable overrides: `dlp_clipboard_in`, `dlp_clipboard_out`, `dlp_upload`, `dlp_download`, `dlp_printing`, `dlp_watermark`, plus `dlp_approval_ref` and `dlp_approved_at`. `NULL` means no override. Defaults (`DLP_DEFAULTS` in `backend/app/services/group_dlp.py`): clipboard in/out on, upload on, download off, printing off, watermark on.

**Approval reference.** An override only counts when `dlp_approval_ref` is non-empty. `PUT /api/groups/{id}/dlp` rejects a body without `approval_ref`. Set and remove are audited (`group.dlp_override`, `group.dlp_override_remove`) with old and new values and the reference. This implements the ADR-0038 amendment.

**Multi-group rule: most restrictive wins.** Only groups with an approval reference take part, and only their non-null fields. For allow-type fields (clipboard, upload, download, printing) the user gets the permission only if every overriding group allows it. For `watermark` it is on if any overriding group wants it.

**Selkies env.** On the Kubernetes launch path only (`group_tier.py`, `launch_overrides` applies `dlp_env`), the policy is set as env on the desktop container, verified against selkies 2.2.0:

| Policy | Env |
|---|---|
| clipboard in/out | `SELKIES_ENABLE_CLIPBOARD` = `true`, `in`, `out` or `false` |
| upload/download | `SELKIES_FILE_TRANSFERS` = `upload`, `download`, `upload,download` or `none` |
| printing | `SELKIES_PRINTING_ENABLED` = `true`/`false` |
| watermark | `STYX_WATERMARK_USER` = username (read by our pixelflux watermark patch, which adds the UTC time) |

These keys (`DLP_ENV_KEYS`, plus the non-Selkies `SELKIES_CLIPBOARD_ENABLED`) are stripped from template env so a template cannot weaken the policy. A watermark needs a non-empty username.

**Gateway filter.** Selkies enforces its settings client-side, so a modified client could ignore them. The agent gateway (`agent/gateway_dlp.py`) drops forbidden clipboard and file messages on the websocket relay in both directions, including gzip-wrapped (opcode 0x05) control text. Currently `gateway.py` does not pass the per-group policy to the filter, so it enforces the ADR-0038 defaults. Per-group overrides are enforced by the Selkies env only. Passing the resolved policy to the gateway is follow-up work.

**Metadata allowlist.** Events carry only: direction (`in`/`out`), channel (`clipboard`/`file`), size in bytes, MIME type (validated against a MIME pattern), and filename. Content is never read or stored. The portal turns the filename into `styx.dlp.filename_sha256` and does not keep the name. `file.hash.*` is not used (ECS means a content hash). The user name comes from the workstation owner, not from the agent payload. The ingest model forbids extra fields.

**Shipping.** The gateway batches events (5 s, 1000 buffered, drop on failure so the relay never blocks) and posts them to `POST /api/agent/dlp-events` (max 500 per call). The portal writes ECS JSON lines (`event.dataset=styx.dlp`, `event.action=<channel>.<direction>`), shipped to the data stream `logs-styx.dlp-*` (`deploy/logging/elastic/index-templates/logs-styx.dlp.json`).

## Alternatives considered

- Strictest-wins also for watermark (off if any group disables it): rejected, a watermark is a protection, so any request for it wins.
- Enforce in Selkies only: rejected, client-side only.
- Hash clipboard content for correlation: rejected, content derivatives make Elastic a CUI store.

## Consequences

Positive:

- Server-side enforcement plus gateway backstop; every override has a recorded approval.
- Events show who moved what kind of data, when and how big, without content.

Negative:

- Per-group DLP env is enforced on the Kubernetes launch path only. The Docker path gets no DLP env and its DLP keys are not locked.
- Gateway enforces defaults only until the policy is passed to it.
- Dropped batches mean lost events (accepted, availability of the desktop wins).
- Allowed clipboard text remains an exfiltration path, as in ADR-0038.

Follow-up work:

- Apply `dlp_env` (and lock DLP keys) on the Docker launch path.
- Pass the resolved per-user policy to the gateway.
- Check that gateway event payload (`allowed` field, `{"events": [...]}` wrapper) matches the ingest endpoint (bare list, no extra fields); see the runbook verification step.
