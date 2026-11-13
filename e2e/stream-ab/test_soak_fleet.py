import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

import fleet  # noqa: E402
import soak_fleet  # noqa: E402


class FakeFleet:
    def __init__(self, fail=False, launch_raises=None):
        self.fail, self.launch_raises = fail, launch_raises
        self.torn = None

    def launch(self, client, n, template, timeout_s, sessions=None, **kw):
        if self.launch_raises:
            if sessions is not None:
                sessions.extend(fleet.Session(name=f"fleet-{i}", id=f"i{i}") for i in range(2))
            raise self.launch_raises
        return [fleet.Session(name=f"fleet-{i}", id=f"i{i}", launch_s=1.0) for i in range(n)]

    def teardown(self, client, sessions):
        self.torn = [s.id for s in sessions]
        return []


def fake_probe(rtt):
    calls = []

    def probe(url, minutes, mode):
        calls.append((url, minutes, mode))
        return {"rtt_ms": [rtt], "drops": 0}
    probe.calls = calls
    return probe


def run(tmp_path, fl, pr, argv=("--sessions", "3", "--minutes", "0.1")):
    a = soak_fleet.parse(list(argv))
    return soak_fleet.run(a, client=object(), fleet_mod=fl, probe_fn=pr, results=tmp_path)


def test_pass_writes_reports_exit0_and_tears_down(tmp_path):
    fl, pr = FakeFleet(), fake_probe(10.0)
    assert run(tmp_path, fl, pr) == 0
    assert fl.torn == ["i0", "i1", "i2"]
    assert len(pr.calls) == 3 and pr.calls[0][1:] == (0.1, "stream")
    js = list(tmp_path.glob("gate-*.json"))
    assert len(js) == 1 and list(tmp_path.glob("gate-*.md"))
    assert json.loads(js[0].read_text())["verdict"] == "pass"


def test_fail_exit1(tmp_path):
    assert run(tmp_path, FakeFleet(), fake_probe(500.0)) == 1


def test_teardown_on_interrupt(tmp_path):
    fl = FakeFleet()

    def boom(*a, **k):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, fl, boom)
    assert fl.torn == ["i0", "i1", "i2"]


def test_teardown_on_interrupt_during_launch(tmp_path):
    fl = FakeFleet(launch_raises=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, fl, fake_probe(10.0))
    assert fl.torn == ["i0", "i1"]


def test_launch_tracks_sessions_on_interrupt():
    class C:
        def request(self, method, path, json=None):
            if method == "POST":
                return {"id": "x-" + json["name"], "status": "running"}
            raise KeyboardInterrupt

    out = []
    with pytest.raises(KeyboardInterrupt):
        fleet.launch(C(), 2, "t", 5, sessions=out)
    assert sorted(s.id for s in out) == ["x-fleet-0", "x-fleet-1"]


def test_session_url_and_http_mode():
    a = soak_fleet.parse(["--sessions", "1", "--minutes", "1", "--probe", "http",
                          "--portal", "https://portal.example.com"])
    assert a.probe == "http"
    assert soak_fleet.session_url(a.portal, "fleet-0") == "https://fleet-0.portal.example.com/"


def test_creds_from_env(monkeypatch):
    monkeypatch.setenv("STYX_USER", "u")
    monkeypatch.setenv("STYX_PASS", "p")
    assert soak_fleet.env_creds() == ("u", "p")
