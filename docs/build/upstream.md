# Upstream contributions

Styx runs on [selkies](https://github.com/selkies-project/selkies) and
[pixelflux](https://github.com/selkies-project/pixelflux). Where we find a defect
or a missing behaviour we write it up and patch it upstream-style, keep the patch
in `docs/upstream/`, and carry a guarded runtime copy until upstream merges.

| # | Target | Problem | Our patch | Downstream carrier |
|---|--------|---------|-----------|--------------------|
| 01 | selkies `src/selkies/websockets_mode.py` (2.1.0) | The page that owns the display is exempt from the video lag gate, so on a jittery link frames pile up (up to the 2 s relay budget) and the congestion controller cuts bitrate hard | [write-up](../upstream/01-selkies-owner-lag-gate.md), [patch](../upstream/01-selkies-owner-lag-gate.patch): owner gets a 100 ms lag threshold and reuses the existing `_lose` / `_repair` path | `agent/shallow_pipe.py::owner_gate`, guarded to selkies 2.2.0 (`_forward` unchanged since 2.1.0) |
| 02a | pixelflux `src/encoders/vaapi/av1.rs` | VA-API AV1 on pre-VCN-5 AMD pads the coded frame and the AV1 header carries no render size | [patch](../upstream/02a-pixelflux-av1-render-size.patch): write `render_and_frame_size_different = 1` with the real size | merged upstream (pixelflux#58), in 2.2.2 |
| 02b | selkies web client (`selkies-core.js` video worker) | Chromium ignores the AV1 render size, so the picture is squeezed or stretched | [patch](../upstream/02b-selkies-av1-crop-client.patch), [write-up](../upstream/02-selkies-av1-crop.md): crop each decoded frame with `visibleRect` | merged upstream (selkies#496), in 2.2.0; downstream copy removed |

## Patched wheels (`EXTRA_WHEELS`)

Where upstream has not released a fix we build a fork wheel with a local version
suffix (`+styxN`). `EXTRA_WHEELS=<dir> scripts/build_agent_artifacts.sh` adds
`--find-links` for that directory, so pip prefers the local `X.Y.Z+styxN` over
PyPI's `X.Y.Z`; the `==X.Y.Z` pin in `enroll.sh` still matches. Python versions
without a patched wheel fall back to PyPI's. Fork: `JMO-Labs/pixelflux`.

* `2.2.1+styx4` (branch `styx/2.2.1`, current): offers the cursor metadata size GNOME/mutter 50 uses (384x384; pixelflux capped at 256x256, so no cursor meta arrived) and makes `pointer_location()` return the host cursor. Feeds the pointer echo behind the locked-pointer cursor ([Agent](agent.md#page-shims-and-webrtc)).

!!! note "Pending: selkies 2.2 (branch `feat/selkies-2.2`, no PR yet)"
    Moves to selkies 2.2.0, pixelflux 2.2.2+styx5 (2.2.2 plus pixelflux#61, host
    pointer echo under portal capture, until a release carries it), pcmflux 2.2.1,
    agent 0.10.0. Upstream merged our work, so the carriers go away:

    * 02a: merged as pixelflux#58, in 2.2.2.
    * 02b: merged as selkies#496, in 2.2.0; `bundle_patch.py` deleted.
    * selkies#489 (still-screen raise): fixed in 2.2.0; `cap_still_raise` deleted.
    * pixelflux#55 (scaled-seat pointer): fixed in 2.2.2, libei used on scaled seats again. Portal Notify still needs the backend's x scale, see GNOME/xdg-desktop-portal-gnome#179.
    * 01 (owner lag gate) stays, guarded to selkies 2.2.0 (`_forward` unchanged since 2.1.0).

## Evidence summary

* **Owner lag gate** (hotel Wi-Fi profile, one session each, agent 0.9.12 vs 0.9.13): bitrate cuts over 30% per 5 min 6.45 -> 0; max extra queue 735 -> 42 ms; p99 116 -> 31 ms. Caveat: different start rates; not a repeated trial.
* **AV1 render size / crop** (Chromium 156, software dav1d): mean absolute pixel error in the padded region fell from 6.2-58.8 to 2.3-2.9 (the codec's own loss is about 2.4). pixelflux `cargo test --lib` and clippy clean.

## Related, tracked upstream

* Still-screen bitrate raise (the "poor connection" sawtooth): selkies#489, fixed in selkies 2.2.0; our `cap_still_raise` wrapper is removed.
* Scale/pointer mapping on a scaled seat: pixelflux#55, fixed in pixelflux 2.2.2 (libei). Portal Notify still needs the backend's x scale (`seat_portal.py`), see GNOME/xdg-desktop-portal-gnome#179.
* Host pointer echo under portal capture: pixelflux#61, merged after 2.2.2; shipped as the `2.2.2+styx5` wheel (2.2.2 + #61) until a release carries it.

## How to add one

1. Reproduce and measure with the [stream harness](streaming.md#latency-and-ab-harness-e2estream-ab).
2. Write `docs/upstream/NN-short-name.md`: target and version, problem, repro, fix, evidence, risk and compat, testing (what was and was not run).
3. Add the `.patch` (`diff -u` against the pinned upstream version).
4. Carry it downstream behind a **version guard** and mark it `ponytail:` so it can be dropped when upstream merges.
