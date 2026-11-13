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


GOOD = {"t0": 100, "dec": 120, "pres": 130, "presCb": 131, "hit": True, "settled": True}
MISS = {"t0": 100, "dec": 120, "pres": None, "presCb": None, "hit": False, "settled": True}


def test_parse_round_real_schema_counts_misses():
    out = json.dumps({"samples": {"key": [GOOD, MISS], "mouse": [GOOD], "motion": []},
                      "sent": {"key": 3, "mouse": 2, "motion": 1}})
    rtt, drops = P.parse_round(out)
    assert rtt == [30.0, 30.0]
    assert drops == 1  # only the pres-null sample; `sent` overhead is ignored


def test_parse_round_null_t0_is_drop():
    rtt, drops = P.parse_round(json.dumps({"samples": {"key": [{"t0": None, "pres": 5}]}}))
    assert rtt == [] and drops == 1


def test_stream_mode_rounds_and_failures():
    c = Clock()
    calls = []
    results = [(0, json.dumps({"samples": {"key": [GOOD, MISS]}, "sent": {"key": 3}})),
               (1, ""), (0, "not json")]

    def run(cmd):
        calls.append(cmd)
        return results[len(calls) - 1]

    res = P.probe("http://s/", 3, "stream", run=run, now=c.now, sleep=c.sleep, round_s=60)
    assert len(calls) == 3
    assert any(a == "--url=http://s/" for a in calls[0])
    assert res == {"rtt_ms": [30.0], "drops": 3}


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
