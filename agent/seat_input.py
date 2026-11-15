"""Input forwarding for the seat portal: RemoteDesktop Notify* passthrough,
press/release reordering and coordinate conversion (system python, dbus-python)."""
import time

import dbus

sessions = {}           # session handle -> Session; shared with seat_portal


REORDER_S = 0.05
PAIRED = ("NotifyPointerButton", "NotifyKeyboardKeycode", "NotifyKeyboardKeysym")


def _ordered(s, name, code, down, send):
    """xdg-desktop-portal can swap a press and release sent back to back (seen
    on stream stutter: release, press -> Mutter keeps the key down, autorepeat).
    A release for something not down waits up to REORDER_S for its press."""
    key, now = (name, code), time.monotonic()
    if down:
        s.down.add(key)
        send(code, True)
        if now - s.early.pop(key, -REORDER_S - 1) <= REORDER_S:
            s.down.discard(key)
            send(code, False)
    elif key in s.down:
        s.down.discard(key)
        send(code, False)
    else:
        s.early[key] = now


def _forward(name, conv):
    """Notify* passthrough with the fixed arity dbus-python needs."""
    def fn2(self, sh, o, a1, a2):
        s = sessions[str(sh)]
        if name in PAIRED:
            _ordered(s, name, *conv(s, o, a1, a2), send=getattr(s.rd, name))
        else:
            getattr(s.rd, name)(*conv(s, o, a1, a2))

    def fn3(self, sh, o, a1, a2, a3):
        s = sessions[str(sh)]
        getattr(s.rd, name)(*conv(s, o, a1, a2, a3))
    return fn3 if name == "NotifyPointerMotionAbsolute" else fn2


def _motion(s, o, dx, dy):
    return dx, dy


def _abs(s, o, stream, x, y):
    # pixelflux divides by its (= the seat's) scale and Mutter divides again:
    # undo pixelflux's, so the pointer lands where the browser's is.
    return s.stream_path, x * s.scale, y * s.scale


def _button(s, o, b, st):
    return b, bool(st)


def _axis(s, o, dx, dy):
    return dx, dy, dbus.UInt32(1 if o.get("finish") else 0)


def _discrete(s, o, axis, n):
    return axis, n


def _key(s, o, k, st):
    return dbus.UInt32(k), bool(st)
