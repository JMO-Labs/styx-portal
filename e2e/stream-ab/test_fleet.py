import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet  # noqa: E402


class FakeClient:
    """In-memory portal. `polls_to_run[name]` = polls before running (None = never)."""

    def __init__(self, polls_to_run=None, fail_create=(), error_names=()):
        self.error_names = set(error_names)
        self.polls_to_run = polls_to_run or {}
        self.fail_create = set(fail_create)
        self.items = {}
        self.deleted = []
        self.calls = []

    def request(self, method, path, json=None):
        self.calls.append((method, path))
        if method == "POST" and path == "/api/instances":
            if json["name"] in self.fail_create:
                raise RuntimeError("boom")
            iid = f"i-{json['name']}"
            self.items[iid] = {"id": iid, "name": json["name"], "status": "starting", "polls": 0}
            return {"id": iid, "status": "starting"}
        iid = path.split("/")[3]
        if method == "POST" and path.endswith("/start"):
            return {"id": iid, "status": "starting"}
        if method == "GET":
            it = self.items[iid]
            it["polls"] += 1
            limit = self.polls_to_run.get(it["name"], 1)
            if it["name"] in self.error_names:
                it["status"] = "error"
            elif limit is not None and it["polls"] >= limit:
                it["status"] = "running"
            return {"id": iid, "status": it["status"]}
        if method == "DELETE":
            self.deleted.append(iid)
            return None
        raise AssertionError((method, path))


def _run(client, n, timeout_s=0.05):
    return fleet.launch(client, n, "tpl", timeout_s, poll_s=0.001)


def test_all_success():
    c = FakeClient()
    s = _run(c, 3, timeout_s=2)
    assert len(s) == 3
    assert all(x.launch_s is not None and x.launch_s >= 0 and x.error is None for x in s)
    assert len({x.id for x in s}) == 3


def test_one_timeout():
    c = FakeClient(polls_to_run={"fleet-1": None})
    s = _run(c, 3)
    by = {x.name: x for x in s}
    assert by["fleet-1"].launch_s is None and "timeout" in by["fleet-1"].error
    assert by["fleet-0"].launch_s is not None and by["fleet-2"].launch_s is not None


def test_create_error_kept():
    c = FakeClient(fail_create={"fleet-0"})
    s = _run(c, 2, timeout_s=2)
    bad = [x for x in s if x.name == "fleet-0"][0]
    assert bad.launch_s is None and "boom" in bad.error and bad.id is None


def test_teardown_deletes_all_even_on_error():
    c = FakeClient()
    s = _run(c, 3, timeout_s=2)
    orig = c.request

    def flaky(method, path, json=None):
        if method == "DELETE" and path.endswith(s[0].id):
            c.deleted.append("tried")
            raise RuntimeError("delete failed")
        return orig(method, path, json)

    c.request = flaky
    errors = fleet.teardown(c, s)
    assert set(c.deleted) >= {s[1].id, s[2].id}
    assert len(errors) == 1


def test_no_start_call_when_starting():
    c = FakeClient()
    _run(c, 2, timeout_s=2)
    assert not [x for x in c.calls if x[1].endswith("/start")]


def test_error_status_is_terminal():
    c = FakeClient(error_names={"fleet-0"})
    s = fleet.launch(c, 1, "tpl", 5, poll_s=0.001)[0]
    assert s.launch_s is None and s.error == "instance status error"
