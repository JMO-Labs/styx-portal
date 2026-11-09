import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import seat_scopes  # noqa: E402


def test_plan_moves_app_trees_skips_infra_and_foreign_shell():
    comm = {10: "gnome-shell", 11: "ibus-daemon", 12: "terminator", 13: "bash",
            14: "claude", 15: "firefox-bin", 20: "gnome-shell", 21: "gdm-app",
            16: "Web Content"}
    kids = {10: [11, 12, 15], 12: [13], 13: [14], 15: [16], 20: [21]}
    seat = {10, 11, 12, 13, 14, 15, 16}   # pid 20 = gdm's shell, not ours
    got = seat_scopes.plan(kids, comm, in_agent=lambda p: p in seat)
    assert got == [("app-styx-terminator-12.scope", [12, 13, 14]),
                   ("app-styx-firefox-bin-15.scope", [15, 16])]


def test_plan_skips_already_moved_and_sanitizes_name():
    comm = {10: "gnome-shell", 12: "moved", 13: "Web Content"}
    kids = {10: [12, 13]}
    got = seat_scopes.plan(kids, comm, in_agent=lambda p: p != 12)
    assert got == [("app-styx-Web_Content-13.scope", [13])]
