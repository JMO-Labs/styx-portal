# ADR-0078: Selkies patch set implementation

- Status: Proposed
- Date: 2026-11-13
- Decision ID: D77
- Related controls: AU-2, AC-11, SI-7, SA-10
- Refines: ADR-0038, ADR-0058, ADR-0067

## Context

The enterprise image needs four behaviours Selkies does not ship: a metadata-only audit line for transfers, a gateway-driven lock, an encoder-burned watermark, and an owner-lag gate. This records how they are carried. Patch notes live in [docs/upstream](../../upstream/README.md).

## Decision

1. **Patches apply at build time.** `images/enterprise-base/Dockerfile` copies `patches/selkies/` and runs `scripts/apply_selkies_patches.sh`, which applies the files listed in `series` in order. A patch that does not apply fails the image build. Patches merged upstream stay in the directory for history but leave `series`; the pinned wheels already carry them.
2. **Audit hook emits the D38 fields.** `03-selkies-audit-hook.patch` writes one JSON line on logger `styx.audit` for clipboard in/out and file upload. Fields are exactly `user`, `time`, `direction`, `size`, `type`, `filename_hash` (sha256, null for clipboard). Never content or the plain filename (ADR-0038). Fluent Bit ships the line.
3. **Lock-overlay hook.** `04-selkies-lock-overlay-hook.patch` adds `STYX_LOCK,<1|0>,<token>`. While locked no video frame is written. Only a message with the shared secret `STYX_LOCK_TOKEN` is applied; with no token every lock message is refused. The gateway sends it (`agent/gateway_lock.py`). Scope is the websockets path only.
4. **Encoder-burned watermark.** `05-pixelflux-watermark.patch` stamps user and UTC time into CPU-path frames before encode, so recordings carry it and the browser cannot disable it. The only input is `STYX_WATERMARK_USER`. It is not in `series` until pixelflux is built from source (#319); the Python spec in `agent/watermark.py` pins the values.
5. **Every patch has a note.** `scripts/check_patch_notes.py` fails CI when a patch in `series` lacks a note with Upstream project, Offered, Status and Reason kept locally.

## Alternatives considered

- Fork Selkies: breaks ADR-0003 (never fork); patches keep the diff small and reviewable.
- Patch at container start: hides failures until runtime and weakens the signed-image story (SI-7).
- Client-side watermark: removable by the user, so not tamper-proof.

## Consequences

Positive: failures surface at build; the diff against upstream is explicit; evidence is tests per patch.

Negative: patches must be rebased on each Selkies bump. The watermark is inactive until #319. The GPU dmabuf path is not stamped.

## Evidence

`agent/tests/test_selkies_audit_hook.py`, `agent/tests/test_gateway_lock.py`, `agent/tests/test_watermark.py`, `backend/tests/test_apply_selkies_patches.py`, `backend/tests/test_patch_notes.py`.
