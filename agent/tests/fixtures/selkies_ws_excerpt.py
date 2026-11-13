# Test fixture: VERBATIM excerpts of selkies 2.2.0 src/selkies/websockets_mode.py with
# patch 01 (owner lag gate) applied, so patch 04 applies to it exactly as to a real install.
# Verbatim: imports (l.41-57), constants (l.262-276), _VideoRelay.offer/_hold/_run
# (l.1428-1550), the websocket TEXT branch head (l.5419-5446).
# Everything marked STUB is the minimal scaffolding the excerpts call into; it is not selkies code.
# Regenerate from the sdist when selkies is bumped (see docs/upstream/04-*.md).

import asyncio
import inspect
import base64
import contextlib
import functools
import gzip
import json
import logging
import os
import struct
import time
import secrets
import socket
import stat
from collections import OrderedDict, deque
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple, Union


# --- STUB: collaborators of the excerpts below ---
class WSMsgType:
    BINARY, TEXT = "binary", "text"
data_logger = type("L", (), {"warning": staticmethod(lambda *a, **k: None)})()
client_permissions = {}
VIEWER_ALLOWED_PREFIXES = ("kd,", "ku,", "m,")
VIEWER_SILENT_DROP_PREFIXES = ()
FRAME_ANCHOR = 0x10
FRAME_NUM_WRAP = 16
WIRE_H264 = 1
VIDEO_RELAY_SENT_MEMORY = 4096
WRITES = []  # (ws, bytes) pairs _send_live was asked to write


async def _send_live(ws, data, what):
    WRITES.append((ws, bytes(data)))


async def ping_behind(ws):
    pass


def _note_send(ds, frame_id, size):
    pass


# trip and VIDEO_RELAY_LAG_SECONDS; past either its link carries less than the
# stream, and the frame is left out. The pings read the queue end to end: a
# proxy or a bloated hop ahead of the page holds one no local count sees.
VIDEO_RELAY_ROOM_FRAMES = 3
VIDEO_RELAY_LAG_SECONDS = 0.1
# The page that owns its display is held to a queue of its own: a delta frame
# is left out (as for any page) once the ping behind its frames has gone
# unanswered this long past the round trip. Anchors and frame_num-wrap frames
# still go. Without it the owner's backlog is bounded only by the relay budget.
VIDEO_RELAY_OWNER_LAG_SECONDS = 0.1
VIDEO_RELAY_PING_SECONDS = 0.05
# Frames a run left out of a page may span before the encoder is told without
# waiting for the page's room: the encoder predicts from the last eight
# (REFERENCE_FRAMES in pixelflux), and the report lands a frame or two late.
VIDEO_RELAY_REACH_FRAMES = 5


class _VideoRelay:  # STUB scaffolding around the verbatim methods
    def __init__(self, server, display_id, ws):
        import asyncio as _a
        from collections import deque as _d
        self.server, self.display_id, self.ws = server, display_id, ws
        self.backlog, self.backlog_bytes, self.budget = _d(), 0, 1 << 30
        self.live_rows, self.sent, self.marks = set(), {}, _d()
        self.written, self.stopped, self.gauged, self.pinged = 0, False, False, 0.0
        self.since_key, self.numbered, self.anchored, self.tracked = 0, False, False, False
        self._wake = _a.Event()

    def _end_lost(self): pass
    def _leave_common(self): pass
    def _judge(self, n): pass
    def _want_sync(self): return False
    def _forward(self, frame_id, reference, anchor=False): return True

    def offer(self, item: dict) -> bool:
        """Accept, drop, or gate one encoded chunk.

        Runs on the event loop and never awaits.

        Args:
            item: The fan-out item (`data` memoryview, `owner` frame,
                `frame_id`).

        Returns:
            True when the caller should request a keyframe (data was dropped
            that only a sync point recovers).
        """
        data = item['data']
        size = len(data)
        is_video = size >= 12 and data[0] == 0x04
        is_idr = is_video and (data[1] & 0x0F) == 0x01
        dropped = False
        flushed = 0
        if (not is_idr and self.backlog
                and self.backlog_bytes + size > self.budget):
            flushed = len(self.backlog)
            self.backlog.clear()
            self.backlog_bytes = 0
            self.live_rows.clear()
            self._end_lost()
            self._leave_common()
            dropped = True
        deliver = True
        if is_video:
            row = (data[4] << 8) | data[5]
            frame_id = (data[2] << 8) | data[3]
            reference = (data[10] << 8) | data[11]
            if not is_idr:
                self.tracked = reference != frame_id
            if is_idr:
                self.since_key = 0
                self.numbered = (data[1] >> 4) == WIRE_H264
                self.anchored = False
                self.live_rows.add(row)
                self._end_lost()
                self.sent.clear()
                for held in (False, True):
                    self.server.common_frames_for(self.display_id, held).join(self)
            elif row not in self.live_rows:
                deliver = False
                dropped = True
            elif reference != frame_id:
                # A whole-frame session names the frame each delta predicts from;
                # a stripe, or a session that cannot say, names its own id.
                self.since_key += 1
                anchor = bool(data[1] & FRAME_ANCHOR)
                self.anchored = self.anchored or anchor
                forward = self._forward(frame_id, reference, anchor)
                deliver = bool(forward)
                if forward is None:
                    self.live_rows.clear()
                    self._end_lost()
                    self._leave_common()
                    dropped = True
        if deliver:
            if is_video:
                self.sent[frame_id] = None
                if len(self.sent) > VIDEO_RELAY_SENT_MEMORY:
                    del self.sent[next(iter(self.sent))]
            self.backlog.append(item)
            self.backlog_bytes += size
            self._wake.set()
            if is_video:
                self._hold(data, held=False)
        self._judge(flushed + (not deliver))
        return dropped and self._want_sync()

    def _hold(self, data: Any, held: bool = True) -> None:
        """This client holds a video frame its relay wrote, or where not `held` was
        handed one its relay queued: a key frame, or a delta frame naming the one
        it predicts from, which this relay sends only where the client holds that
        one (`CommonFrames`). A relay that drops its queue leaves both."""
        frame_id = (data[2] << 8) | data[3]
        key = (data[1] & 0x0F) == 0x01
        if (((data[4] << 8) | data[5]) in self.live_rows
                and (key or ((data[10] << 8) | data[11]) != frame_id)):
            self.server.common_frames_for(self.display_id, held).hold(self, frame_id, key)

    async def _run(self) -> None:
        """Drain the backlog onto the socket until stopped or the socket dies."""
        try:
            while True:
                if self.stopped:
                    return
                if not self.backlog:
                    self._wake.clear()
                    await self._wake.wait()
                    continue
                item = self.backlog.popleft()
                data = item['data']
                self.backlog_bytes -= len(data)
                self.written += len(data)
                self.marks.append(self.written)
                # Stamped before the await, and only for the display's
                # registered client: that is what the ACK RTT math measures, and
                # the hand to the socket is where its stats read a frame as sent.
                ds = self.server.display_clients.get(self.display_id)
                if ds is not None and ds.get('ws') is self.ws:
                    _note_send(ds, item['frame_id'], len(data))
                    watch = self.server._stream_watches.get(self.display_id)
                    if watch is not None:
                        watch.note_send(getattr(item.get('owner'), 'capture_ns', 0), len(data))
                try:
                    await _send_live(self.ws, data, f"Video relay for '{self.display_id}'")
                    if len(data) >= 12 and data[0] == 0x04 and not self.stopped:
                        self._hold(data)
                    if self.gauged and time.monotonic() - self.pinged >= VIDEO_RELAY_PING_SECONDS:
                        self.pinged = time.monotonic()
                        await ping_behind(self.ws)
                except (ConnectionResetError, OSError, RuntimeError):
                    self.server.clients.discard(self.ws)
                    return
        finally:
            group = self.server.video_relay_groups.get(self.display_id)
            if group is not None and group.get(self.ws) is self:
                del group[self.ws]



class DataStreamingServer:  # STUB scaffolding around the verbatim TEXT branch
    def __init__(self):
        self.display_clients = {"primary": {}}
        self.idr_requests = []

    def _schedule_idr_for_display(self, display_id):
        self.idr_requests.append(display_id)

    async def ws_handler(self, websocket, remote_address, msgs):
        handled = []
        for msg in msgs:
            if True:
                if msg.type == WSMsgType.BINARY:
                    pass

                elif msg.type == WSMsgType.TEXT:
                    message = msg.data
                    if message == "_gz,1":
                        # Echoed so the client gzips its own large sends too.
                        websocket._ws_gz = True
                        try:
                            await websocket.send_str("_gz,1")
                        except Exception:
                            pass
                        continue
                    perms = client_permissions.get(websocket)
                    if perms and perms.get("role") == "viewer":
                        # Authority lists shared with the WebRTC gate: the collab extras
                        # need enable_collab on, even for a viewer holding the mk token.
                        allowed_viewer_prefixes: tuple[str, ...] = VIEWER_ALLOWED_PREFIXES
                        if settings.enable_collab[0] and sessions.active_mk_token and perms.get("token") == sessions.active_mk_token:
                            allowed_viewer_prefixes = allowed_viewer_prefixes + VIEWER_COLLAB_EXTRA_PREFIXES
                        if not message.startswith(allowed_viewer_prefixes):
                            # A viewer's blur/visibility noise (kr would clobber the
                            # controller's held modifiers) is refused silently: a warning
                            # per blur floods the log.
                            if not message.startswith(VIEWER_SILENT_DROP_PREFIXES):
                                data_logger.warning(f"DENIED unauthorized message from viewer {remote_address}: {message[:100]}...")
                            continue

                    if message.startswith("SETTINGS,"):
                        try:
                            _, payload_str = message.split(",", 1)

                            handled.append(message)
                        except Exception:
                            pass
        return handled
