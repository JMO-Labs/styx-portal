import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_probe as P  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def run_ok(samples, sent=None):
    out = json.dumps({"samples": samples, "sent": sent or {k: len(v) for k, v in samples.items()}})
    return lambda cmd: (0, out)


def test_parse_round_flattens_and_counts_misses():
    out = json.dumps({"samples": {"key": [10.0, None], "mouse": [20.0], "motion": []},
                      "sent": {"key": 2, "mouse": 3, "motion": 0}})
    rtt, drops = P.parse_round(out)
    assert rtt == [10.0, 20.0]
    assert drops == 1 + 2  # one null + two mouse samples never reported


def test_stream_mode_rounds_and_failures():
    c = Clock()
    calls = []
    results = [(0, json.dumps({"samples": {"key": [5.0, 6.0]}, "sent": {"key": 2}})),
               (1, ""), (0, "not json")]

    def run(cmd):
        calls.append(cmd)
        return results[len(calls) - 1]

    res = P.probe("http://s/", 3, "stream", run=run, now=c.now, sleep=c.sleep, round_s=60)
    assert len(calls) == 3
    assert any(a == "--url=http://s/" for a in calls[0])
    assert res == {"rtt_ms": [5.0, 6.0], "drops": 2}


def test_stream_mode_exception_is_drop():
    def run(cmd):
        raise TimeoutError

    c = Clock()
    res = P.probe("u", 1, "stream", run=run, now=c.now, sleep=c.sleep, round_s=60)
    assert res == {"rtt_ms": [], "drops": 1}


def test_http_mode_rtt_and_drops():
    c = Clock()
    n = {"i": 0}

    def get(url, timeout):
        n["i"] += 1
        if n["i"] % 3 == 0:
            raise OSError("boom")
        c.t += 0.05
        return 200

    res = P.probe("http://s/", 0.1, "http", get=get, now=c.now, sleep=c.sleep)
    assert res["drops"] == 2 and len(res["rtt_ms"]) == 4
    assert all(abs(r - 50.0) < 1e-6 for r in res["rtt_ms"])


def test_http_5xx_is_drop():
    c = Clock()
    res = P.probe("u", 0.05, "http", get=lambda u, timeout: 503, now=c.now, sleep=c.sleep)
    assert res["rtt_ms"] == [] and res["drops"] > 0


def test_bad_mode():
    try:
        P.probe("u", 1, "x")
    except ValueError:
        return
    raise AssertionError
