# Emit a metadata-only D38 audit line for clipboard and file transfers

- **Upstream project:** selkies-project/selkies
- **Offered:** not yet
- **Status:** local-only
- **Reason kept locally:** Styx-specific event shape (ADR-0038 D38 fields, stdout JSON line for Fluent Bit); upstream already offers `audit_webhook_url` for the same transfers.

Target: selkies 2.2.0, `selkies/audit.py` plus a new `selkies/styx_audit.py`.
Patch: `patches/selkies/03-selkies-audit-hook.patch` (apply with `git apply` or `patch -p1` from the package parent dir).

## What it does

`audit.emit` already runs at every clipboard in/out and file upload site. The patch calls `styx_audit.on_event(event, fields)` first. It maps `clipboard.receive` (in), `clipboard.send` (out) and `file.upload.end` (in) to one JSON line on logger `styx.audit` (stdout, same style as `backend/app/services/audit_ecs.py`). Other events are ignored.

Fields, exactly: `user`, `time`, `direction`, `size`, `type`, `filename_hash` (sha256 of the filename, null for clipboard). Never content or the plain filename. `user` is read from `STYX_AUDIT_USER` (null if unset). For files, `type` is guessed from the extension.

## Risk / compat

- Runs even without `audit_webhook_url`; it is a no-op for other events and adds one log line per transfer.
- File download is not covered (out of scope for this ticket).
- Test: `agent/tests/test_selkies_audit_hook.py` builds the module from the patch and checks the field set.
