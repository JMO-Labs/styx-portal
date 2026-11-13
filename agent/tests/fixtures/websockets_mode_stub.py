# Minimal stand-in for selkies 2.1.0 websockets_mode.py after patches 01..02b.
# Only the lines patch 04 anchors on; keeps the patch test runnable without selkies.
VIDEO_RELAY_ROOM_FRAMES = 3
VIDEO_RELAY_LAG_SECONDS = 0.1
VIDEO_RELAY_OWNER_LAG_SECONDS = 0.1
VIDEO_RELAY_PING_SECONDS = 0.05


class _VideoRelay:
    def __init__(self, server=None, ws=None, display_id="p"):
        self.server, self.ws, self.display_id = server, ws, display_id
        self.gauged = False
        self.sent = []

    def _lose(self, frame_id):
        pass

    def _repair(self):
        return None

    def _lag(self):
        return 0.0

    def _forward(self, frame_id, frame, kept=False, anchor=False):
        if self.server._owns_display(self.ws, self.display_id):
            self.gauged = True
            if kept or anchor or self._lag() < VIDEO_RELAY_OWNER_LAG_SECONDS:
                self.sent.append(frame)
                return True
            self._lose(frame_id)
            return self._repair()
        self.sent.append(frame)
        return True
