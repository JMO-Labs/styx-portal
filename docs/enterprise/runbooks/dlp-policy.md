# DLP policy runbook

Operate data loss prevention for desktops (ADR-0038, ADR-0070). Events are metadata only, never content.

## Defaults

| Setting | Default |
|---|---|
| Clipboard in / out | allowed |
| File upload (in) | allowed |
| File download (out) | blocked |
| Printing | blocked |
| Watermark (user and time) | on |

## Set a group override

A written approval from the security officer is required first. Record its reference (ticket or document id).

1. Admin API, as an admin:
   ```bash
   curl -X PUT "$PORTAL/api/groups/$GROUP_ID/dlp" \
     -H 'Content-Type: application/json' \
     -d '{"download": true, "approval_ref": "SO-2026-014"}'
   ```
   Fields: `clipboard_in`, `clipboard_out`, `upload`, `download`, `printing`, `watermark`. Omitted or `null` means no override. `approval_ref` is required; without it the call fails with 422.
2. The response shows `override`, `approval_ref`, `approved_at` and `effective` for that group.
3. The change is audited as `group.dlp_override` (old and new values, approval reference).

If a user is in several groups, the most restrictive value wins: a permission needs every overriding group to allow it; the watermark is on if any group wants it. Groups without an approval reference are ignored.

Overrides apply when a desktop is launched, on the Kubernetes runtime only. The Docker launch path does not set the DLP env and does not lock the DLP keys (ADR-0070 follow-up). Restart running desktops to pick up a change.

## Remove an override

```bash
curl -X DELETE "$PORTAL/api/groups/$GROUP_ID/dlp"
```

All fields return to the defaults and the approval reference is cleared. Audited as `group.dlp_override_remove`. Read the current state with `GET` on the same path.

## Verify enforcement

1. Check the effective policy: `GET /api/groups/$GROUP_ID/dlp`, field `effective`.
2. On Kubernetes, check the desktop container env after launch (Docker desktops do not get these): `SELKIES_ENABLE_CLIPBOARD`, `SELKIES_FILE_TRANSFERS`, `SELKIES_PRINTING_ENABLED`, `STYX_WATERMARK_USER` (absent when the watermark is off).
3. In a session, try a download and a print job (blocked by default). The watermark must show user and time.
4. The agent gateway also drops forbidden clipboard and file messages. It currently enforces the defaults only (ADR-0070).

## Find events in Elastic

Data view `logs-styx.dlp-*`, filter `event.dataset: "styx.dlp"`.

| Field | Meaning |
|---|---|
| `event.action` | `clipboard.in`, `clipboard.out`, `file.in`, `file.out` |
| `user.name` | Desktop owner |
| `file.size`, `file.mime_type` | Size in bytes and MIME type |
| `styx.dlp.filename_sha256` | SHA-256 of the file name |

No content, and no plain file names, are stored. Override changes are in the audit stream (`event.dataset: "styx.audit"`, action `group.dlp_override*`).

No events although transfers happened: check the agent log for `dlp-events post failed` and the portal log for 422 on `/api/agent/dlp-events`.
