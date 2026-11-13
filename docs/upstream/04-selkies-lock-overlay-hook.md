# Lock-overlay hook: blank the video stream on command

- **Upstream project:** selkies-project/selkies
- **Offered:** not yet
- **Status:** local-only
- **Reason kept locally:** Styx-specific lock policy (gateway-driven); not written up for upstream.

Target: selkies-project/selkies, `src/selkies/websockets_mode.py`, selkies 2.2.0 (the version `scripts/build_agent_artifacts.sh` pins).
Patch: `patches/selkies/04-selkies-lock-overlay-hook.patch` (`diff -u` against 2.2.0 with patch 01 applied; apply after 01 with `patch -p1` from the package parent dir, i.e. paths are `selkies/websockets_mode.py`).

## What it does

Adds `LOCK` and `handle_lock_command()`. While locked, no video frame is written to any page:

- `_VideoRelay.offer` refuses video chunks, and
- `_VideoRelay._run`, the one place frames are written to the socket, discards video queued before the lock.

The text message `STYX_LOCK,<1|0>,<token>` is handled in the websocket TEXT branch before the viewer permission filter. Only a message carrying the shared secret `STYX_LOCK_TOKEN` (environment, known to the gateway and selkies only) is applied. A viewer or controller page on the same websocket cannot lock or unlock; with no token configured every lock message is refused. Each applied command requests a key frame so the stream resumes cleanly. The gateway sends it (`agent/gateway_lock.py::send_lock`).

## Tests

`agent/tests/test_gateway_lock.py` applies the patch to `agent/tests/fixtures/selkies_ws_excerpt.py`: verbatim excerpts of the real 2.2.0 functions (`offer`, `_hold`, `_run`, the TEXT branch head) with minimal stubs around them, and checks the written frames and the dispatch path.

## Caveats

- Frames are withheld, not replaced by a synthetic black frame (an encoder-agnostic blank cannot be written into a delta stream). The page keeps its last picture until the Styx overlay covers it; client-side overlay rendering is not covered here.
- Only the websockets data path is gated; the WebRTC mode is not.
