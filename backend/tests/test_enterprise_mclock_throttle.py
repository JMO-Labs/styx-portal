"""Business-hours mClock recovery throttle (issue #29)."""

import importlib.util
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "mclock_throttle",
    ROOT / "deploy/enterprise/rook-ceph/throttle/mclock_throttle.py",
)
mt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mt)

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
WINDOW = mt.parse_window("Mon-Fri 07:00-19:00 America/New_York")
CLIENT, RECOVERY = "high_client_ops", "high_recovery_ops"


def ny(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=NY)


@pytest.mark.parametrize(
    "now,expected",
    [
        (ny(2026, 11, 2, 6, 59), RECOVERY),  # Mon
        (ny(2026, 11, 2, 7, 0), CLIENT),
        (ny(2026, 11, 6, 18, 59), CLIENT),  # Fri
        (ny(2026, 11, 6, 19, 0), RECOVERY),
        (ny(2026, 11, 7, 12, 0), RECOVERY),  # Sat
        (ny(2026, 11, 8, 12, 0), RECOVERY),  # Sun
        # DST edges, given as UTC instants
        (datetime(2026, 3, 8, 12, 0, tzinfo=UTC), RECOVERY),  # Sun, 08:00 EDT
        (datetime(2026, 11, 1, 12, 0, tzinfo=UTC), RECOVERY),  # Sun, 07:00 EST
        (datetime(2026, 3, 9, 11, 0, tzinfo=UTC), CLIENT),  # Mon 07:00 EDT
        (datetime(2026, 11, 2, 12, 0, tzinfo=UTC), CLIENT),  # Mon 07:00 EST
        (datetime(2026, 11, 2, 11, 59, tzinfo=UTC), RECOVERY),  # Mon 06:59 EST
    ],
)
def test_profile_for_schedule(now, expected):
    assert mt.profile_for(now, WINDOW, "") == expected


def test_dst_dates_07_ny_client_when_weekday_window_all_days():
    w = mt.parse_window("Mon-Sun 07:00-19:00 America/New_York")
    assert mt.profile_for(datetime(2026, 3, 8, 11, 0, tzinfo=UTC), w, "") == CLIENT
    assert mt.profile_for(datetime(2026, 11, 1, 12, 0, tzinfo=UTC), w, "") == CLIENT


def test_force_override_wins():
    sat = ny(2026, 11, 7, 12, 0)
    assert mt.profile_for(sat, WINDOW, CLIENT) == CLIENT
    mon = ny(2026, 11, 2, 9, 0)
    assert mt.profile_for(mon, WINDOW, RECOVERY) == RECOVERY


def test_invalid_force_ignored_with_warning(caplog):
    mon = ny(2026, 11, 2, 9, 0)
    with caplog.at_level(logging.WARNING):
        got = mt.profile_for(mon, WINDOW, "balanced; rm -rf /")
    assert got == CLIENT
    assert "invalid" in caplog.text.lower()


class FakeRunner:
    def __init__(self, current="", fail=False):
        self.current, self.fail, self.calls = current, fail, []

    def __call__(self, argv):
        assert isinstance(argv, list)
        self.calls.append(argv)
        if self.fail:
            raise RuntimeError("boom")
        if argv[:3] == ["ceph", "config", "get"]:
            return self.current + "\n"
        return ""


ENV = {"THROTTLE_WINDOW": "Mon-Fri 07:00-19:00 America/New_York", "THROTTLE_FORCE": ""}
MON_9AM = ny(2026, 11, 2, 9, 0)


def test_sets_when_different():
    r = FakeRunner(current=RECOVERY)
    assert mt.main(env=ENV, runner=r, now=MON_9AM) == 0
    assert ["ceph", "config", "set", "osd", "osd_mclock_profile", CLIENT] in r.calls


def test_no_set_when_equal():
    r = FakeRunner(current=CLIENT)
    assert mt.main(env=ENV, runner=r, now=MON_9AM) == 0
    assert not [c for c in r.calls if c[:3] == ["ceph", "config", "set"]]


def test_runner_failure_nonzero():
    assert mt.main(env=ENV, runner=FakeRunner(fail=True), now=MON_9AM) != 0


def test_main_uses_force_env():
    r = FakeRunner(current=CLIENT)
    env = {**ENV, "THROTTLE_FORCE": RECOVERY}
    assert mt.main(env=env, runner=r, now=MON_9AM) == 0
    assert r.calls[-1][-1] == RECOVERY


def test_default_runner_uses_no_shell(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen.update(argv=argv, **kw)

        class P:
            stdout = "x"

        return P()

    monkeypatch.setattr(mt.subprocess, "run", fake_run)
    mt.run_ceph(["ceph", "config", "get", "osd", "osd_mclock_profile"])
    assert isinstance(seen["argv"], list)
    assert not seen.get("shell")
    assert seen["check"] is True
