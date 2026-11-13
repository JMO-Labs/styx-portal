# Lock-overlay hook: blank the video stream on command

- **Upstream project:** selkies-project/selkies
- **Offered:** not yet
- **Status:** local-only
- **Reason kept locally:** Styx-specific lock policy (gateway-driven); not written up for upstream.

Target: `src/selkies/websockets_mode.py`. Patch: `patches/selkies/04-selkies-lock-overlay-hook.patch` (applies after 01..02b with `patch -p1`).

## What it does

Adds `LOCK`, `set_lock()` and `handle_lock_command()`. The text command `STYX_LOCK,1` blanks the stream: `_VideoRelay._forward` emits `BLANK_FRAME` instead of desktop frames. `STYX_LOCK,0` resumes real frames. The gateway sends the command (`agent/gateway_lock.py::send_lock`).

## Caveats

- Written against the context lines of patch 01, not a full selkies checkout; `agent/tests/test_gateway_lock.py` applies it to a stub (`agent/tests/fixtures/websockets_mode_stub.py`). Verify the send path and wire `handle_lock_command` into selkies' text-message dispatch on a real 2.2.0 install.
- Client rendering of an empty frame (black vs last picture) is not covered.
