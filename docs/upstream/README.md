# Upstream patch index

Patches live in `patches/selkies/` (apply order in `series`). Every patch has a note `docs/upstream/<patch-name>.md` with the fields Upstream project, Offered, Status, Reason kept locally. `scripts/check_patch_notes.py` enforces this.

| Patch | Upstream project | Status | Note |
|---|---|---|---|
| `01-selkies-owner-lag-gate.patch` | selkies-project/selkies | local-only | [note](01-selkies-owner-lag-gate.md) |
| `02a-pixelflux-av1-render-size.patch` | selkies-project/pixelflux | merged (pixelflux#58) | [note](02a-pixelflux-av1-render-size.md) |
| `02b-selkies-av1-crop-client.patch` | selkies-project/selkies | merged (selkies#496) | [note](02b-selkies-av1-crop-client.md) |
| `05-pixelflux-watermark.patch` | selkies-project/pixelflux | local-only | [note](05-pixelflux-watermark.md) |

Other write-ups: [02-selkies-av1-crop.md](02-selkies-av1-crop.md), [03-drafts-2026-11-01.md](03-drafts-2026-11-01.md).
