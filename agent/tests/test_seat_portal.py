import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import seat_portal  # needs system dbus-python + PyGObject + Gst typelib
except (ImportError, ValueError):
    pytest.skip("seat_portal needs dbus-python/PyGObject/Gst", allow_module_level=True)


def test_selftest_method_tables():
    assert seat_portal.selftest() == 0


def test_parse_size():
    assert seat_portal.parse_size("2552x1294") == (2552, 1294)
    for bad in ("0x10", "axb", "1920"):
        with pytest.raises(ValueError):
            seat_portal.parse_size(bad)


def test_ordered_fixes_swapped_press_release():
    # xdg-desktop-portal delivered 'e' as release, press: Mutter kept it down.
    s, sent = type("S", (), {"down": set(), "early": {}})(), []
    send = lambda code, down: sent.append((code, down))  # noqa: E731
    seat_portal._ordered(s, "K", 101, False, send)   # early release: held back
    assert sent == []
    seat_portal._ordered(s, "K", 101, True, send)    # its press: press + release
    assert sent == [(101, True), (101, False)]
    sent.clear()
    seat_portal._ordered(s, "K", 32, True, send)     # in-order pair untouched
    seat_portal._ordered(s, "K", 32, False, send)
    assert sent == [(32, True), (32, False)]
    sent.clear()
    seat_portal._ordered(s, "K", 7, False, send)     # stale stray release
    s.early[("K", 7)] -= 1
    seat_portal._ordered(s, "K", 7, True, send)      # later hold stays held
    assert sent == [(7, True)]


def test_caps_fps_default_and_clamp():
    assert "max-framerate=60/1" in seat_portal.caps(1920, 1080)
    assert "width=1920,height=1080,max-framerate=120/1" in seat_portal.caps(1920, 1080, 120)
    assert seat_portal.parse_fps(None) == 60
    assert seat_portal.parse_fps("0") == 1
    assert seat_portal.parse_fps("9999") == 240
    assert seat_portal.parse_fps("junk") == 60


def test_main_argv_fps_flag():
    assert seat_portal.parse_args(["p", "800x600"]) == (800, 600, 60)
    assert seat_portal.parse_args(["p", "800x600", "--max-fps", "120"]) == (800, 600, 120)


def test_max_fps_as_last_arg_falls_back():
    assert seat_portal.parse_args(["p", "800x600", "--max-fps"]) == (800, 600, 60)


def test_source_types():
    assert seat_portal.source_types({}) == 1
    assert seat_portal.source_types({"types": 1}) == 1
    assert seat_portal.source_types({"types": 4}) == 4
    assert seat_portal.source_types({"types": 5}) == 4


def test_abs_routes_by_node():
    s = type("S", (), {"paths": {7: "/p/stream7"}, "stream_path": "/p/primary", "scale": 2.0})()
    assert seat_portal._abs(s, {}, 7, 10.0, 20.0) == ("/p/stream7", 20.0, 40.0)
    assert seat_portal._abs(s, {}, 9, 10.0, 20.0) == ("/p/primary", 20.0, 40.0)


def test_stream_entry_names_node_geometry_and_source_type():
    node, d = seat_portal.stream_entry(76, {"position": (0, 1318), "size": (2556, 1302)}, 4)
    assert int(node) == 76 and int(d["source_type"]) == 4
    assert tuple(d["position"]) == (0, 1318) and tuple(d["size"]) == (2556, 1302)
    _, d = seat_portal.stream_entry(5, {"mapping-id": "x"}, 1)
    assert "position" not in d and "size" not in d   # unknown stays unknown, never 0x0
    assert int(d["source_type"]) == 1


def test_monitor_names_its_logical_geometry():
    """Mutter's virtual stream Parameters carry only a mapping-id; the seat
    monitor supplies its logical size (pixels over the seat scale)."""
    assert seat_portal.logical_geometry({"mapping-id": "x"}, 2556, 1302, 1.0) == {
        "mapping-id": "x", "position": (0, 0), "size": (2556, 1302)}
    assert seat_portal.logical_geometry({}, 2556, 1302, 2.0)["size"] == (1278, 651)
    kept = {"position": (0, 1318), "size": (10, 10)}
    assert seat_portal.logical_geometry(kept, 2556, 1302, 1.0) == kept


def test_monitor_hands_its_stream_over_and_takes_it_back(monkeypatch):
    """Two readers of a virtual monitor fight over its format: the size holder
    lets go while the capture reads it, and holds it again after."""
    class Pipe:
        def set_state(self, s):
            self.state = s
    launched = []
    monkeypatch.setattr(seat_portal.Gst, "parse_launch", lambda d: launched.append(d) or Pipe())
    m = object.__new__(seat_portal.Monitor)
    m.w, m.h, m.fps, m.node, m.pipe, m.playing = 800, 600, 60, 7, None, False
    m.hold()
    assert m.pipe is not None and "path=7" in launched[-1] and "width=800,height=600" in launched[-1]
    m.hold()
    assert len(launched) == 1                      # already holding: no second reader
    m.release()
    assert m.pipe is None
    m.release()
    m.w, m.h = 1024, 700
    m.hold()
    assert len(launched) == 2 and "width=1024,height=700" in launched[-1]


def test_a_closing_session_lets_go_of_what_it_holds():
    """The seat's RemoteDesktop session outlives each selkies, so a capture
    killed mid-drag or with Ctrl held must release them on Close."""
    sent = []

    class RD:
        def NotifyKeyboardKeycode(self, code, state): sent.append(("key", int(code), bool(state)))
        def NotifyPointerButton(self, code, state): sent.append(("btn", int(code), bool(state)))
    s = type("S", (), {"rd": RD(), "down": {("NotifyKeyboardKeycode", 29),
                                            ("NotifyPointerButton", 272)}})()
    seat_portal.release_held(s)
    assert sorted(sent) == [("btn", 272, False), ("key", 29, False)] and not s.down
